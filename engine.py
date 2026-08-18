"""
Portfolio calculation engine (shared by CLI and web app).
Pure functions: no printing, no I/O side effects beyond the network fetch.
"""

import sys
from datetime import datetime

import pandas as pd

try:
    import yfinance as yf
except ImportError:
    yf = None


COLUMN_ALIASES = {
    "ticker":    {"ticker", "symbol", "stock"},
    "shares":    {"shares", "quantity", "qty", "units"},
    "buy_price": {"buy_price", "cost", "price", "purchase_price",
                  "avg_price", "cost_basis"},
    "buy_date":  {"buy_date", "date", "purchase_date"},
}


def load_portfolio_df(df):
    """Normalize a raw DataFrame (already read from CSV) into canonical columns."""
    df = df.copy()
    df.columns = [str(c).strip().lower().replace(" ", "_") for c in df.columns]

    rename = {}
    for canonical, aliases in COLUMN_ALIASES.items():
        for col in df.columns:
            if col in aliases:
                rename[col] = canonical
                break
    df = df.rename(columns=rename)

    # buy_price / buy_date are optional: without them the app runs in "period
    # mode" (performance + CAGR of the current holdings over a chosen window).
    for required in ("ticker", "shares"):
        if required not in df.columns:
            raise ValueError(
                f"CSV is missing a column for '{required}'. "
                f"Found: {list(df.columns)}"
            )

    df["ticker"] = df["ticker"].astype(str).str.strip().str.upper()
    df["shares"] = pd.to_numeric(df["shares"], errors="coerce")
    if "buy_price" in df.columns:
        df["buy_price"] = pd.to_numeric(df["buy_price"], errors="coerce")
    else:
        df["buy_price"] = pd.NA
    if "buy_date" in df.columns:
        df["buy_date"] = pd.to_datetime(df["buy_date"], errors="coerce")
    else:
        df["buy_date"] = pd.NaT

    df = df.dropna(subset=["ticker", "shares"])
    return df


def has_cost_basis(df):
    """True when at least one holding has a buy price (cost-basis mode)."""
    return bool(pd.to_numeric(df["buy_price"], errors="coerce").notna().any())


# Trailing-return windows (key -> approximate calendar days back).
TRAILING_PERIODS = {
    "1m": 30,
    "3m": 91,
    "6m": 182,
    "1y": 365,
    "3y": 1095,
    "5y": 1825,
    "10y": 3650,
}

# Human-friendly labels for each window key (used by the UI / column headers).
PERIOD_LABELS = {
    "1m": "1M", "3m": "3M", "6m": "6M", "1y": "1Y",
    "3y": "3Y", "5y": "5Y", "10y": "10Y",
}

# Nominal length of each window in years (for annualizing / CAGR).
PERIOD_YEARS = {k: d / 365.25 for k, d in TRAILING_PERIODS.items()}


def history_period_for(period_keys):
    """Smallest yfinance history period string that safely covers the longest
    selected window (needs a real datapoint at, not just up to, the cutoff)."""
    max_days = max((TRAILING_PERIODS[k] for k in period_keys), default=365)
    if max_days <= 366:
        return "2y"
    if max_days <= 3 * 366:
        return "5y"
    if max_days <= 5 * 366:
        return "10y"
    return "max"


def annualize(cum_pct, period_key):
    """Annualize a cumulative % return over the given window into a CAGR %.

    Returns None for sub-year windows (annualizing them is misleading) or when
    the cumulative return is missing. For a single-entry asset (e.g. an index)
    this equals its XIRR over the window.
    """
    if cum_pct is None or pd.isna(cum_pct) or TRAILING_PERIODS[period_key] < 365:
        return None
    return ((1 + cum_pct / 100) ** (1 / PERIOD_YEARS[period_key]) - 1) * 100


def _asof(asof):
    return (asof if asof is not None else pd.Timestamp.now()).normalize()


def _xnpv(rate, flows, t0):
    """Net present value of dated cash flows at an annual `rate`."""
    rate = max(rate, -0.999999)
    return sum(a / (1 + rate) ** ((d - t0).days / 365.25) for d, a in flows)


def xirr(flows):
    """Annualized money-weighted return (fraction) for dated cash flows.

    `flows` = [(date, amount), ...] with at least one negative (money invested)
    and one positive (value returned). Solved by bisection so staggered entry
    dates are handled exactly. Returns None if it can't be solved.
    """
    flows = [(pd.Timestamp(d), float(a)) for d, a in flows if a is not None]
    if len(flows) < 2:
        return None
    amts = [a for _, a in flows]
    if not (any(a > 0 for a in amts) and any(a < 0 for a in amts)):
        return None
    t0 = min(d for d, _ in flows)
    lo, hi = -0.9999, 10.0
    f_lo, f_hi = _xnpv(lo, flows, t0), _xnpv(hi, flows, t0)
    tries = 0
    while f_lo * f_hi > 0 and hi < 1e7 and tries < 80:
        hi *= 1.5
        f_hi = _xnpv(hi, flows, t0)
        tries += 1
    if f_lo * f_hi > 0:
        return None
    for _ in range(200):
        mid = (lo + hi) / 2
        f_mid = _xnpv(mid, flows, t0)
        if abs(f_mid) < 1e-7:
            return mid
        if f_lo * f_mid < 0:
            hi, f_hi = mid, f_mid
        else:
            lo, f_lo = mid, f_mid
    return (lo + hi) / 2


def fetch_history(tickers, period="2y"):
    """Return {ticker: Series of adjusted closes indexed by date}.

    Fetches enough history (default 2y) to derive both the latest price and
    the trailing returns. Robust to non-trading days and bad tickers.
    """
    if yf is None:
        raise RuntimeError("yfinance not installed - cannot fetch live prices.")
    history = {}
    for t in tickers:
        try:
            hist = yf.Ticker(t).history(period=period, auto_adjust=True)
            closes = hist["Close"].dropna() if not hist.empty else pd.Series(dtype=float)
            if closes.empty:
                print(f"  ! no data for {t}", file=sys.stderr)
                continue
            history[t] = closes
        except Exception as e:
            print(f"  ! failed {t}: {e}", file=sys.stderr)
    return history


def _trailing_return_pct(closes, days):
    """% change from the close ~`days` ago to the latest close.

    Uses the most recent trading day on or before the cutoff, so it is robust
    to weekends/holidays. Returns None if history doesn't reach that far back.
    """
    if closes is None or closes.empty:
        return None
    latest_price = float(closes.iloc[-1])
    cutoff = closes.index[-1] - pd.Timedelta(days=days)
    past = closes[closes.index <= cutoff]
    if past.empty:
        return None
    past_price = float(past.iloc[-1])
    if past_price <= 0:
        return None
    return (latest_price / past_price - 1) * 100


def prices_from_history(history):
    """Latest close per ticker: {ticker: last_close}."""
    return {t: float(closes.iloc[-1]) for t, closes in history.items()}


def trailing_returns_from_history(history, periods=None):
    """{ticker: {period_key: pct}} for the requested periods (values may be None).

    `periods` is a list of TRAILING_PERIODS keys; defaults to all of them.
    """
    keys = list(periods) if periods else list(TRAILING_PERIODS)
    return {
        t: {k: _trailing_return_pct(closes, TRAILING_PERIODS[k]) for k in keys}
        for t, closes in history.items()
    }


def fetch_market_data(tickers):
    """Fetch history once; return (prices, trailing_returns)."""
    history = fetch_history(tickers)
    return prices_from_history(history), trailing_returns_from_history(history)


def fetch_prices(tickers):
    """Return {ticker: last_available_close}. Kept for backward compatibility."""
    return prices_from_history(fetch_history(tickers))


# Benchmark indices (label -> yfinance symbol).
BENCHMARKS = {
    "NIFTY 50": "^NSEI",
    "S&P 500":  "^GSPC",
    "NASDAQ":   "^IXIC",
}


def fetch_benchmarks(period="2y"):
    """Return {label: closes} for the benchmark indices (label-keyed, not symbol)."""
    symbol_hist = fetch_history(list(BENCHMARKS.values()), period=period)
    return {label: symbol_hist[sym]
            for label, sym in BENCHMARKS.items() if sym in symbol_hist}


def _date_indexed(closes):
    """Re-key a close series on naive calendar dates so series from different
    exchanges/timezones can be aligned on the same axis."""
    idx = pd.to_datetime(closes.index)
    if idx.tz is not None:
        idx = idx.tz_localize(None)
    out = closes.copy()
    out.index = idx.normalize()
    return out


def _normalize(closes):
    """Rebase a series to 100 at its first point; return a plain list of floats."""
    base = float(closes.iloc[0])
    if base == 0:
        return [None] * len(closes)
    return [round(float(v) / base * 100, 2) for v in closes]


def aggregate_holdings(df):
    """Total shares per ticker (a ticker may appear in several rows)."""
    return df.groupby("ticker")["shares"].sum()


def portfolio_value_series(df, history):
    """Market value of the *current* holdings over time (buy-and-hold of today's
    composition). `history` is {ticker: closes}. Keeps only dates where every
    priced holding has data."""
    shares = aggregate_holdings(df)
    cols = {}
    for t, n in shares.items():
        if t in history and not history[t].empty:
            cols[t] = _date_indexed(history[t]) * float(n)
    if not cols:
        return pd.Series(dtype=float)
    aligned = pd.concat(cols, axis=1).sort_index().dropna()
    if aligned.empty:
        return pd.Series(dtype=float)
    return aligned.sum(axis=1)


def portfolio_trailing_returns(df, history, periods=None):
    """Trailing returns (requested periods) of the current portfolio's value series."""
    keys = list(periods) if periods else list(TRAILING_PERIODS)
    port = portfolio_value_series(df, history)
    return {k: _trailing_return_pct(port, TRAILING_PERIODS[k]) for k in keys}


def _window_entry(closes, start):
    """(entry_date, entry_price) for a holding within a window: its price at the
    window start, or its first available (listing) price if it listed later.
    None if the holding has no data on/after the window start."""
    avail = _date_indexed(closes)
    avail = avail[avail.index >= start]
    if avail.empty:
        return None
    px = float(avail.iloc[0])
    return (avail.index[0], px) if px > 0 else None


def portfolio_window_metrics(df, history, prices, periods=None, asof=None):
    """Per-period money-weighted cumulative return and XIRR of the current
    holdings. Each holding enters at the window start or its listing date
    (whichever is later), valued at that date's price; today's total value is the
    terminal inflow. Robust to holdings with only partial history in the window.

    Returns {"returns": {key: cum_pct}, "xirr": {key: xirr_pct}} (values may be None).
    """
    keys = list(periods) if periods else list(TRAILING_PERIODS)
    asof = _asof(asof)
    shares = aggregate_holdings(df)
    ret, xr = {}, {}
    for k in keys:
        start = asof - pd.Timedelta(days=TRAILING_PERIODS[k])
        total_entry = total_now = 0.0
        flows = []
        for t, n in shares.items():
            cur = prices.get(t)
            if cur is None or t not in history or history[t].empty:
                continue
            entry = _window_entry(history[t], start)
            if entry is None:
                continue
            entry_date, entry_px = entry
            total_entry += float(n) * entry_px
            total_now += float(n) * cur
            flows.append((entry_date, -float(n) * entry_px))
        if total_entry <= 0 or not flows:
            ret[k] = xr[k] = None
            continue
        ret[k] = (total_now / total_entry - 1) * 100
        earliest = min(d for d, _ in flows)
        # Only annualize when the oldest holding spans ~a year of the window.
        if TRAILING_PERIODS[k] >= 365 and (asof - earliest).days >= 330:
            r = xirr(flows + [(asof, total_now)])
            xr[k] = r * 100 if r is not None else None
        else:
            xr[k] = None
    return {"returns": ret, "xirr": xr}


def stock_window_xirr(closes, current_price, window_days, asof=None):
    """Annualized return of one holding over the window, entering at the window
    start or its listing date. None if its available span is under a year."""
    if current_price is None or closes is None or closes.empty:
        return None
    asof = _asof(asof)
    entry = _window_entry(closes, asof - pd.Timedelta(days=window_days))
    if entry is None:
        return None
    entry_date, entry_px = entry
    days = (asof - entry_date).days
    if days < 365:  # don't annualize a sub-year holding period
        return None
    return ((current_price / entry_px) ** (365.25 / days) - 1) * 100


def portfolio_xirr_cost(result, asof=None):
    """Portfolio XIRR in cost-basis mode: each holding's -cost_basis at its
    buy_date plus today's total value. Holdings without a buy_date are excluded."""
    asof = _asof(asof)
    flows, total_now = [], 0.0
    for _, r in result.iterrows():
        bd, cb, cv = r.get("buy_date"), r.get("cost_basis"), r.get("current_value")
        if pd.notna(bd) and cb and cv is not None and pd.notna(cv):
            flows.append((pd.Timestamp(bd).normalize(), -float(cb)))
            total_now += float(cv)
    if not flows:
        return None
    r = xirr(flows + [(asof, total_now)])
    return r * 100 if r is not None else None


def stock_cagr_from_listing(closes, current_price, asof=None):
    """Per-holding CAGR from the first date data exists (usually the listing
    date) to today. None if under a year of history."""
    if current_price is None or closes is None or closes.empty:
        return None
    asof = _asof(asof)
    c = _date_indexed(closes).dropna()
    if c.empty:
        return None
    first_date, first_px = c.index[0], float(c.iloc[0])
    days = (asof - first_date).days
    # ~11.5 months+ so a share listed "about a year ago" still gets a CAGR, but
    # clearly sub-year listings (which annualize misleadingly) stay blank.
    if first_px <= 0 or days < 350:
        return None
    return ((current_price / first_px) ** (365.25 / days) - 1) * 100


def portfolio_cashflows(df, result, holding_history, prices, mode, asof=None):
    """The portfolio's investment stream as [(date, amount_invested), ...] plus
    the terminal value today.

    Cost mode: each holding's cost_basis at its buy_date.
    Period mode: each holding's market value at its listing date (buy-and-hold of
    today's shares since the stock first had data).
    """
    asof = _asof(asof)
    flows, terminal = [], 0.0
    if mode == "cost":
        for _, r in result.iterrows():
            bd, cb, cv = r.get("buy_date"), r.get("cost_basis"), r.get("current_value")
            if pd.notna(bd) and cb and cv is not None and pd.notna(cv):
                flows.append((pd.Timestamp(bd).normalize(), float(cb)))
                terminal += float(cv)
    else:
        shares = aggregate_holdings(df)
        for t, n in shares.items():
            cur = prices.get(t)
            if cur is None or t not in holding_history or holding_history[t].empty:
                continue
            c = _date_indexed(holding_history[t]).dropna()
            if c.empty or float(c.iloc[0]) <= 0:
                continue
            flows.append((c.index[0], float(n) * float(c.iloc[0])))
            terminal += float(n) * cur
    return flows, terminal


def _xirr_of_stream(invest_flows, terminal, asof):
    if not invest_flows or terminal <= 0:
        return None
    r = xirr([(d, -a) for d, a in invest_flows] + [(asof, terminal)])
    return r * 100 if r is not None else None


def benchmark_matched_xirr(invest_flows, bench_closes, asof=None):
    """XIRR if the SAME cash flows (same amounts, same dates) had been invested
    into the benchmark index: buy index units on each date, value them today."""
    asof = _asof(asof)
    if not invest_flows or bench_closes is None or bench_closes.empty:
        return None
    b = _date_indexed(bench_closes).dropna()
    if b.empty:
        return None

    def level_on_or_before(d):
        s = b[b.index <= d]
        return float(s.iloc[-1]) if not s.empty else None

    today_level = level_on_or_before(asof) or float(b.iloc[-1])
    units, flows = 0.0, []
    for d, amt in invest_flows:
        lvl = level_on_or_before(d)
        if lvl and lvl > 0:
            units += amt / lvl
            flows.append((d, -amt))
    if not flows or units <= 0:
        return None
    r = xirr(flows + [(asof, units * today_level)])
    return r * 100 if r is not None else None


def xirr_comparison(df, result, holding_history, benchmark_history, prices, mode,
                    asof=None):
    """Single money-weighted XIRR for the portfolio and each benchmark, using the
    portfolio's actual cash-flow stream. Returns [{"label":..., "xirr":...}, ...]."""
    asof = _asof(asof)
    invest_flows, terminal = portfolio_cashflows(df, result, holding_history,
                                                 prices, mode, asof)
    rows = [{"label": "Portfolio", "xirr": _xirr_of_stream(invest_flows, terminal, asof)}]
    for label, closes in benchmark_history.items():
        rows.append({"label": label,
                     "xirr": benchmark_matched_xirr(invest_flows, closes, asof)})
    return rows


def comparison_series(df, holding_history, benchmark_history, window_days=365):
    """Base-100 growth of the portfolio vs each benchmark over the trailing
    window. Returns {"dates": [iso...], "series": {label: [values...]}} with
    every benchmark reindexed onto the portfolio's trading dates."""
    port = portfolio_value_series(df, holding_history)
    if port.empty:
        return {"dates": [], "series": {}}

    cutoff = port.index[-1] - pd.Timedelta(days=window_days)
    port = port[port.index >= cutoff]
    if len(port) < 2:
        return {"dates": [], "series": {}}

    dates = port.index
    series = {"Portfolio": _normalize(port)}
    for label, closes in benchmark_history.items():
        aligned = _date_indexed(closes).reindex(dates).ffill().bfill()
        if aligned.notna().all():
            series[label] = _normalize(aligned)

    return {"dates": [d.strftime("%Y-%m-%d") for d in dates], "series": series}


def benchmark_summary(df, holding_history, benchmark_history, prices,
                      periods=None, asof=None):
    """Return + XIRR rows for the portfolio and each benchmark, ready to render:
    [{"label": ..., "returns": {key: pct}, "xirr": {key: pct}}, ...].

    The Portfolio row is money-weighted (per-holding dated entry), so holdings
    with only partial history don't distort it. A benchmark is a single-entry
    asset, so its XIRR is just the annualized form of its cumulative return.
    """
    keys = list(periods) if periods else list(TRAILING_PERIODS)
    pm = portfolio_window_metrics(df, holding_history, prices, keys, asof)
    rows = [{"label": "Portfolio", "returns": pm["returns"], "xirr": pm["xirr"]}]
    bench_returns = trailing_returns_from_history(benchmark_history, keys)
    for label in benchmark_history:
        ret = bench_returns[label]
        rows.append({"label": label, "returns": ret,
                     "xirr": {k: annualize(ret.get(k), k) for k in keys}})
    return rows


def compute_metrics(df, prices, returns=None, periods=None):
    returns = returns or {}
    keys = list(periods) if periods else list(TRAILING_PERIODS)
    rows = []
    for _, r in df.iterrows():
        t = r["ticker"]
        cur = prices.get(t)
        buy_price = r["buy_price"]
        has_bp = pd.notna(buy_price)
        cost_basis = (r["shares"] * float(buy_price)) if has_bp else None
        tr = returns.get(t, {})

        # With a buy date, only report windows that fall within the holding
        # period; longer windows predate ownership, so blank them. XIRR is then
        # annualized over the same holding period (below).
        held_days = ((datetime.now() - r["buy_date"].to_pydatetime()).days
                     if pd.notna(r["buy_date"]) else None)
        years_held = held_days / 365.25 if held_days is not None else None
        row_returns = {
            k: (None if (held_days is not None and TRAILING_PERIODS[k] > held_days)
                else tr.get(k))
            for k in keys
        }

        row = {
            "ticker": t, "shares": r["shares"],
            "buy_price": float(buy_price) if has_bp else None,
            "buy_date": r["buy_date"],
            "cost_basis": cost_basis, "current_price": cur,
            "returns": row_returns,
        }
        if cur is None:
            row.update(current_value=None, weight_pct=None, abs_return=None,
                       abs_return_pct=None, years_held=years_held, cagr_pct=None)
            rows.append(row)
            continue

        current_value = r["shares"] * cur
        abs_return = abs_return_pct = None
        if cost_basis is not None:
            abs_return = current_value - cost_basis
            abs_return_pct = (abs_return / cost_basis * 100) if cost_basis else None

        # Per-holding XIRR = annualized return over the holding period (single buy).
        # Only annualized for holdings held a year or more (matches window rule).
        cagr_pct = None
        if held_days is not None and cost_basis and cost_basis > 0 and held_days >= 365:
            cagr_pct = ((current_value / cost_basis) ** (365.25 / held_days) - 1) * 100

        row.update(current_value=current_value, weight_pct=None, abs_return=abs_return,
                   abs_return_pct=abs_return_pct, years_held=years_held,
                   cagr_pct=cagr_pct)
        rows.append(row)

    # Portfolio weight of each priced holding (share of current market value).
    total_value = sum(r["current_value"] for r in rows if r["current_value"] is not None)
    if total_value:
        for r in rows:
            if r["current_value"] is not None:
                r["weight_pct"] = r["current_value"] / total_value * 100
    return pd.DataFrame(rows)


def portfolio_summary(result):
    priced = result.dropna(subset=["current_value"])
    total_value = float(priced["current_value"].sum())

    costs = priced["cost_basis"].dropna()
    has_cost = not costs.empty
    total_cost = float(costs.sum()) if has_cost else None
    total_return = (total_value - total_cost) if has_cost else None
    total_return_pct = (total_return / total_cost * 100) if (has_cost and total_cost) else None

    port_cagr = None
    if has_cost and total_cost and total_cost > 0:
        dated = priced.dropna(subset=["years_held", "cost_basis"])
        if not dated.empty:
            w_years = (dated["years_held"] * dated["cost_basis"]).sum() / dated["cost_basis"].sum()
            if w_years > 0:
                port_cagr = ((total_value / total_cost) ** (1 / w_years) - 1) * 100

    return {
        "total_cost": total_cost, "total_value": total_value,
        "total_return": total_return, "total_return_pct": total_return_pct,
        "portfolio_cagr_pct": port_cagr, "has_cost": has_cost,
        "n_priced": int(len(priced)), "n_total": int(len(result)),
    }
