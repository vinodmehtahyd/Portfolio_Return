"""Signal gathering for the recommendation agent.

Technical signals come from the price history we already fetched (no extra
network). Fundamental signals (quarterly revenue) need a yfinance call, which is
why they run in the on-demand Recommendation step rather than during Analyze.

Everything degrades gracefully: missing/short history or unavailable fundamentals
yield None fields, and the rules that consume them simply contribute 0.
"""
import pandas as pd

try:
    import yfinance as yf
except ImportError:
    yf = None


# ----------------------------- technical (d) -----------------------------

def _rsi(closes, period=14):
    delta = closes.diff().dropna()
    if len(delta) < period:
        return None
    gain = delta.clip(lower=0).rolling(period).mean().iloc[-1]
    loss = (-delta.clip(upper=0)).rolling(period).mean().iloc[-1]
    if pd.isna(gain) or pd.isna(loss):
        return None
    if loss == 0:
        return 100.0
    rs = gain / loss
    return float(100 - 100 / (1 + rs))


def technical_signals(closes):
    """Medium-term trend from moving averages. Fields are None when there isn't
    enough history (e.g. a 200-day SMA needs ~200 trading days)."""
    out = {"price": None, "sma50": None, "sma200": None,
           "pct_vs_200dma": None, "trend": None, "rsi14": None}
    if closes is None or getattr(closes, "empty", True):
        return out
    c = closes.dropna()
    if c.empty:
        return out
    price = float(c.iloc[-1])
    out["price"] = price
    if len(c) >= 50:
        out["sma50"] = float(c.rolling(50).mean().iloc[-1])
    if len(c) >= 200:
        sma200 = float(c.rolling(200).mean().iloc[-1])
        out["sma200"] = sma200
        out["pct_vs_200dma"] = (price / sma200 - 1) * 100 if sma200 else None
    out["rsi14"] = _rsi(c, 14)

    if out["sma200"] is not None and out["sma50"] is not None:
        if price > out["sma200"] and out["sma50"] > out["sma200"]:
            out["trend"] = "Uptrend"
        elif price < out["sma200"] and out["sma50"] < out["sma200"]:
            out["trend"] = "Downtrend"
        else:
            out["trend"] = "Mixed"
    return out


# ---------------------------- fundamental (b) ----------------------------

def fetch_quarterly_revenue(ticker):
    """[(quarter_date, revenue), ...] oldest->newest, or None. Defensive against
    yfinance's variable fundamentals shapes / spotty coverage."""
    if yf is None:
        return None
    try:
        tk = yf.Ticker(ticker)
        df = None
        for attr in ("quarterly_income_stmt", "quarterly_financials"):
            cand = getattr(tk, attr, None)
            if cand is not None and getattr(cand, "empty", True) is False:
                df = cand
                break
        if df is None:
            return None
        row = None
        for name in ("Total Revenue", "TotalRevenue", "Revenue", "Operating Revenue"):
            if name in df.index:
                row = df.loc[name]
                break
        if row is None:
            return None
        s = pd.to_numeric(row, errors="coerce").dropna().sort_index()
        return [(d, float(v)) for d, v in s.items()] or None
    except Exception:
        return None


def revenue_signals(ticker, fetch=None):
    """Latest and prior year-over-year revenue growth + a trend label.
    {"rev_yoy_pct", "prev_yoy_pct", "rev_trend"} (Accelerating/Decelerating/Steady)."""
    out = {"rev_yoy_pct": None, "prev_yoy_pct": None, "rev_trend": None}
    series = (fetch or fetch_quarterly_revenue)(ticker)
    if not series or len(series) < 5:
        return out
    vals = [v for _, v in series]  # oldest -> newest

    def yoy(i):
        if i - 4 < 0 or vals[i - 4] == 0:
            return None
        return (vals[i] / vals[i - 4] - 1) * 100

    n = len(vals)
    latest, prev = yoy(n - 1), (yoy(n - 2) if n >= 6 else None)
    out["rev_yoy_pct"], out["prev_yoy_pct"] = latest, prev
    if latest is not None and prev is not None:
        if latest > prev + 1:
            out["rev_trend"] = "Accelerating"
        elif latest < prev - 1:
            out["rev_trend"] = "Decelerating"
        else:
            out["rev_trend"] = "Steady"
    return out


def gather_signals(df, holding_history):
    """{ticker: {"tech": {...}, "fund": {...}}} for each holding."""
    return {t: {"tech": technical_signals(holding_history.get(t)),
                "fund": revenue_signals(t)}
            for t in df["ticker"].unique()}
