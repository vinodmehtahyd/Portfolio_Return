"""Recommendation criteria as small, independent functions.

Each rule takes a `ctx` dict and returns (score_delta, reason_or_None). To add a
new criterion: write a function with the same shape and append it to RULES. The
scoring/aggregation logic in core.py never needs to change.

ctx keys: stock_ret, bench_ret, port_ret (percent, may be None), cagr (may be
None), weight (percent, may be None), reference (benchmark label), plabel
(window label, e.g. "5Y"), cfg (merged config dict).
"""


def beat_benchmark(ctx):
    """Average out/under-performance vs the benchmark across the 3 shortest
    (short/medium-term) windows."""
    rel, m = ctx.get("rel_bench"), ctx["cfg"]["beat_margin_pct"]
    if rel is None or not ctx["reference"]:
        return 0, None
    win = ctx.get("short_label", "short/medium term")
    if rel >= m:
        return 1, f"Beat {ctx['reference']} across {win} by {rel:+.1f}% (avg)."
    if rel <= -m:
        return -1, f"Lagged {ctx['reference']} across {win} by {rel:+.1f}% (avg)."
    return 0, None


def beat_portfolio(ctx):
    """Average out/under-performance vs the portfolio across the short windows."""
    rel, m = ctx.get("rel_port"), ctx["cfg"]["beat_margin_pct"]
    if rel is None:
        return 0, None
    win = ctx.get("short_label", "short/medium term")
    if rel >= m:
        return 1, f"Beat the portfolio across {win} by {rel:+.1f}% (avg)."
    if rel <= -m:
        return -1, f"Lagged the portfolio across {win} by {rel:+.1f}% (avg)."
    return 0, None


def cagr_quality(ctx):
    cagr, c = ctx["cagr"], ctx["cfg"]
    if cagr is None:
        return 0, None
    if cagr >= c["cagr_good_pct"]:
        return 1, f"Strong long-term CAGR ({cagr:.1f}%)."
    if cagr <= c["cagr_poor_pct"]:
        return -1, f"Weak long-term CAGR ({cagr:.1f}%)."
    return 0, None


def concentration(ctx):
    w, cap = ctx["weight"], ctx["cfg"]["max_weight_pct"]
    if w is not None and w > cap:
        return -1, f"Overweight at {w:.1f}% (cap {cap:.0f}%)."
    return 0, None


def technical_trend(ctx):
    """(d) Medium-term price trend from the 50/200-day moving averages."""
    tech = ctx.get("tech") or {}
    trend, pct = tech.get("trend"), tech.get("pct_vs_200dma")
    tail = f" ({pct:+.0f}% vs 200-DMA)" if pct is not None else ""
    if trend == "Uptrend":
        return 1, f"Medium-term uptrend{tail}."
    if trend == "Downtrend":
        return -1, f"Medium-term downtrend{tail}."
    return 0, None


def revenue_growth(ctx):
    """(b) Quarterly revenue growth (YoY) and whether it's accelerating."""
    fund = ctx.get("fund") or {}
    yoy, trend, c = fund.get("rev_yoy_pct"), fund.get("rev_trend"), ctx["cfg"]
    if yoy is None:
        return 0, None
    note = f", {trend.lower()}" if trend else ""
    if yoy >= c["rev_good_pct"] and trend != "Decelerating":
        return 1, f"Revenue +{yoy:.0f}% YoY{note}."
    if yoy <= c["rev_poor_pct"] or trend == "Decelerating":
        return -1, f"Revenue {yoy:+.0f}% YoY{note}."
    return 0, None


# The active criteria. Append new rule functions here to extend the agent.
RULES = [beat_benchmark, beat_portfolio, cagr_quality, concentration,
         technical_trend, revenue_growth]
