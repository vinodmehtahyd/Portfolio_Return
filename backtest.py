"""Backtest the recommendation agent, and compare how often to rebalance.

Modular — reuses engine + recommender read-only; edits nothing.

Method (point-in-time, to avoid look-ahead):
  * Start at `start` (today - start_days_ago); value today's holdings at that
    date's prices -> starting weights.
  * Rebalance strategy: on each rebalance date, run the agent on data available
    only up to that date and apply its suggested weight changes; hold until the
    next rebalance date. Chain the returns to today.
  * Compare: Baseline (never rebalance) vs Monthly vs Quarterly vs the benchmarks.

Caveats: the revenue rule is EXCLUDED (yfinance gives only today's fundamentals,
not point-in-time). No costs/taxes; current holdings assumed to exist at `start`
(later listings excluded). Past performance != future.
"""
import sys

import pandas as pd

import engine
import recommender
from recommender import signals as sig

DEFAULT_PERIODS = ["1y", "3y", "5y"]


def _at(s, d):
    """Most recent value of a date-indexed series on or before d, else None."""
    x = s[s.index <= d]
    return float(x.iloc[-1]) if len(x) else None


def _trailing(s, d, periods):
    sd = s[s.index <= d]
    return {p: engine._trailing_return_pct(sd, engine.TRAILING_PERIODS[p]) for p in periods}


def _asof_weights(shares, H, d):
    """Current-composition weights (%) valued at prices as of d."""
    vals = {t: n * _at(H[t], d) for t, n in shares.items()
            if t in H and _at(H[t], d) is not None}
    tot = sum(vals.values())
    return {t: v / tot * 100 for t, v in vals.items()} if tot else {}


def _agent_weights(current, d, H, B, port_series, periods, config):
    """New target weights (%) after the agent rebalances `current` (%) as of d."""
    avail = {t: w for t, w in current.items() if t in H and _at(H[t], d) is not None}
    if not avail:
        return current

    bench_rows = [{"label": "Portfolio", "returns": _trailing(port_series, d, periods)}]
    for label, b in B.items():
        if _at(b, d) is not None:
            bench_rows.append({"label": label, "returns": _trailing(b, d, periods)})

    rows, sigs, cagrs = [], {}, {}
    for t, w in avail.items():
        sd = H[t][H[t].index <= d]
        cagr = engine.stock_cagr_from_listing(sd, float(sd.iloc[-1]), asof=d)
        rows.append({"ticker": t, "current_value": max(w, 1e-9), "weight_pct": w,
                     "returns": _trailing(H[t], d, periods), "cagr_pct": cagr})
        sigs[t] = {"tech": sig.technical_signals(sd), "fund": {}}
        cagrs[t] = cagr

    recos = recommender.recommend_portfolio(pd.DataFrame(rows), bench_rows, periods,
                                            cagrs, config=config, signals=sigs)
    raw = {x["ticker"]: max(0.0, current.get(x["ticker"], 0.0) + x["suggested_delta"])
           for x in recos}
    for t, w in current.items():        # untradable-at-d holdings keep their weight
        raw.setdefault(t, w)
    tot = sum(raw.values())
    return {t: v / tot * 100 for t, v in raw.items()} if tot else current


def _rolling(shares, H, B, port_series, start, now, step_days, periods, config):
    """Total return (%) of the agent strategy rebalanced every `step_days`."""
    dates, d = [], start
    while d < now:
        dates.append(d)
        d = d + pd.Timedelta(days=step_days)

    w = _asof_weights(shares, H, start)
    if not w:
        return None, 0
    w = _agent_weights(w, dates[0], H, B, port_series, periods, config)
    value, prev = 1.0, dates[0]
    for i in range(1, len(dates) + 1):
        d = dates[i] if i < len(dates) else now
        grown = {t: w[t] / 100 * _at(H[t], d) / _at(H[t], prev)
                 for t in w if _at(H[t], prev)}
        growth = sum(grown.values())
        value *= growth
        prev = d
        if i < len(dates):                 # rebalance (not at the final 'now')
            drifted = {t: g / growth * 100 for t, g in grown.items()}
            w = _agent_weights(drifted, d, H, B, port_series, periods, config)
    return (value - 1) * 100, len(dates)


def compare_frequencies(df, periods=None, start_days_ago=365, config=None):
    """Baseline vs Monthly vs Quarterly rebalancing vs benchmarks over the window."""
    periods = periods or DEFAULT_PERIODS
    now = pd.Timestamp.now().normalize()
    start = now - pd.Timedelta(days=start_days_ago)

    shares = df.groupby("ticker")["shares"].sum()
    hist = engine.fetch_history(list(shares.index), period="max")
    benchmark_history = engine.fetch_benchmarks(period="max")
    H = {t: engine._date_indexed(hist[t]).dropna() for t in shares.index if t in hist}
    B = {label: engine._date_indexed(c).dropna() for label, c in benchmark_history.items()}
    port_series = engine.portfolio_value_series(df, hist)

    w0 = _asof_weights(shares, H, start)
    if not w0:
        return None
    baseline = (sum(w0[t] / 100 * _at(H[t], now) / _at(H[t], start) for t in w0) - 1) * 100
    monthly, n_m = _rolling(shares, H, B, port_series, start, now, 30, periods, config)
    quarterly, n_q = _rolling(shares, H, B, port_series, start, now, 91, periods, config)
    bench = {label: (_at(b, now) / _at(b, start) - 1) * 100
             for label, b in B.items() if _at(b, start)}

    return {
        "start": start.date().isoformat(), "today": now.date().isoformat(),
        "start_days_ago": start_days_ago, "periods": periods,
        "step_pct": recommender.RECO_CONFIG.get("step_pct"),
        "baseline_return_pct": baseline,
        "monthly_return_pct": monthly, "monthly_rebalances": n_m,
        "quarterly_return_pct": quarterly, "quarterly_rebalances": n_q,
        "benchmark_return_pct": bench,
        "excluded": [t for t in shares.index if t not in w0],
    }


def format_comparison(rep):
    if rep is None:
        return "Backtest: no holdings could be evaluated (no data at the start date)."
    L = [f"Rebalance-frequency backtest — {rep['start']} to {rep['today']} "
         f"(~{rep['start_days_ago']}d), agent step {rep['step_pct']}%/move",
         f"  Periods: {', '.join(rep['periods'])}   (revenue rule excluded — no point-in-time fundamentals)",
         ""]
    def line(name, ret, extra=""):
        return f"  {name:24}: {ret:+.1f}%{extra}" if ret is not None else f"  {name:24}: n/a"
    L.append(line("Baseline (never rebalance)", rep["baseline_return_pct"]))
    L.append(line("Monthly rebalance", rep["monthly_return_pct"],
                  f"   ({rep['monthly_rebalances']} rebalances)"))
    L.append(line("Quarterly rebalance", rep["quarterly_return_pct"],
                  f"   ({rep['quarterly_rebalances']} rebalances)"))
    L.append("")
    for label, r in rep["benchmark_return_pct"].items():
        L.append(line(label, r))
    if rep["excluded"]:
        L.append(f"\n  Excluded (not listed at start): {', '.join(rep['excluded'])}")
    return "\n".join(L)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: python backtest.py <portfolio.csv> [start_days_ago] [periods e.g. 1y,3y,5y]")
        sys.exit(1)
    path = sys.argv[1]
    days = int(sys.argv[2]) if len(sys.argv) > 2 else 365
    periods = sys.argv[3].split(",") if len(sys.argv) > 3 else DEFAULT_PERIODS
    portfolio = engine.load_portfolio_df(pd.read_csv(path))
    print(format_comparison(compare_frequencies(portfolio, periods=periods, start_days_ago=days)))
