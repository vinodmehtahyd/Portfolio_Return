"""Recommendation agent core: build each holding's context, run the rules,
score, and choose Reduce / Increase / No change plus a weight suggestion.

Consumes only what `engine` already produces (the metrics DataFrame and the
benchmark rows) — it imports `engine` read-only and never modifies it.
"""
import pandas as pd

import engine
from .config import merged
from .rules import RULES


def _num(x):
    return None if x is None or pd.isna(x) else float(x)


def _reco(ticker, weight, action, score, cagr, ref, delta, reasons,
          short_label=None, stock_short=None, rel_bench=None, rel_port=None,
          tech=None, fund=None):
    return {
        "ticker": ticker, "weight_pct": weight, "action": action, "score": score,
        "cagr": cagr, "reference": ref, "suggested_delta": delta, "reasons": reasons,
        "short_label": short_label, "stock_short": stock_short,
        "rel_bench": rel_bench, "rel_port": rel_port,
        "tech": tech or {}, "fund": fund or {},
    }


def recommend_portfolio(result, bench_rows, periods, cagr_by_ticker=None,
                        config=None, signals=None):
    """Return a list of recommendation dicts (sorted Increase -> No change ->
    Reduce). `result` is engine.compute_metrics() output; `bench_rows` is
    engine.benchmark_summary() output; `cagr_by_ticker` maps ticker -> CAGR %;
    `signals` maps ticker -> {"tech": {...}, "fund": {...}} (see signals.py)."""
    cfg = merged(config)
    cagr_by_ticker = cagr_by_ticker or {}
    signals = signals or {}

    by_label = {row["label"]: (row.get("returns") or {}) for row in bench_rows}
    port_returns = by_label.get("Portfolio", {})
    ref = cfg["reference_benchmark"]
    if ref not in by_label:
        others = [r["label"] for r in bench_rows if r["label"] != "Portfolio"]
        ref = others[0] if others else None
    ref_returns = by_label.get(ref, {}) if ref else {}

    # Benchmark/portfolio comparison uses the 3 shortest selected windows
    # (short/medium term), averaged.
    short_keys = sorted(periods, key=lambda k: engine.TRAILING_PERIODS[k])[:3]
    short_label = "/".join(engine.PERIOD_LABELS.get(k, k) for k in short_keys)

    recos = []
    for _, r in result.iterrows():
        t = r["ticker"]
        if _num(r.get("current_value")) is None:
            continue
        weight = _num(r.get("weight_pct"))
        rets = r.get("returns") or {}
        sig = signals.get(t, {})
        tech, fund = sig.get("tech") or {}, sig.get("fund") or {}
        cagr = cagr_by_ticker.get(t)
        if cagr is None:
            cagr = _num(r.get("cagr_pct"))

        # Average relative performance vs the benchmark and the portfolio across
        # the short windows (only where both values exist).
        rel_b, rel_p, s_ret = [], [], []
        for p in short_keys:
            sr = _num(rets.get(p))
            if sr is None:
                continue
            s_ret.append(sr)
            b, pr = _num(ref_returns.get(p)), _num(port_returns.get(p))
            if b is not None:
                rel_b.append(sr - b)
            if pr is not None:
                rel_p.append(sr - pr)
        rel_bench = sum(rel_b) / len(rel_b) if rel_b else None
        rel_port = sum(rel_p) / len(rel_p) if rel_p else None
        stock_short = sum(s_ret) / len(s_ret) if s_ret else None

        if not any(_num(rets.get(p)) is not None for p in periods):
            recos.append(_reco(t, weight, "No change", 0, cagr, ref, 0.0,
                               ["Not enough price history to assess."],
                               short_label=short_label, tech=tech, fund=fund))
            continue

        ctx = {
            "rel_bench": rel_bench, "rel_port": rel_port, "cagr": cagr,
            "weight": weight, "reference": ref, "short_label": short_label,
            "cfg": cfg, "tech": tech, "fund": fund,
        }

        score, reasons = 0, []
        for rule in RULES:
            delta, reason = rule(ctx)
            score += delta
            if reason:
                reasons.append(reason)

        if score >= cfg["increase_score"]:
            action = "Increase"
        elif score <= cfg["reduce_score"]:
            action = "Reduce"
        else:
            action = "No change"

        step = cfg.get("step_pct", 2.0)
        suggest = 0.0
        if action == "Increase":
            suggest = step
        elif action == "Reduce":
            over = weight is not None and weight > cfg["max_weight_pct"]
            suggest = -(weight - cfg["max_weight_pct"]) if over else -min(step, (weight or 0) * 0.5)
        if not reasons:
            reasons.append("In line with the benchmark and portfolio — hold.")

        recos.append(_reco(t, weight, action, score, cagr, ref, suggest, reasons,
                           short_label=short_label, stock_short=stock_short,
                           rel_bench=rel_bench, rel_port=rel_port, tech=tech, fund=fund))

    order = {"Increase": 0, "No change": 1, "Reduce": 2}
    recos.sort(key=lambda x: (order[x["action"]], -x["score"]))
    return recos


def summarize(recos):
    """Counts per action, e.g. {"Increase": 2, "No change": 1, "Reduce": 1}."""
    return {a: sum(1 for x in recos if x["action"] == a)
            for a in ("Increase", "No change", "Reduce")}
