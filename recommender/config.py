"""Editable knobs for the recommendation agent (v1, rule-based).

Every threshold the agent uses lives here, so its conditions can be reviewed and
tuned in one place. (Whether to move these to a YAML file the user edits without
code is parked for a later iteration.)
"""

RECO_CONFIG = {
    "beat_margin_pct": 5.0,      # out/under-performance band vs benchmark & portfolio
    "cagr_good_pct": 15.0,       # "strong" long-term compounding
    "cagr_poor_pct": 5.0,        # "weak" long-term compounding
    "max_weight_pct": 25.0,      # single-position concentration cap
    "step_pct": 6.0,             # weight nudge per Increase/Reduce (3x the original 2%)
    "rev_good_pct": 12.0,        # "strong" YoY quarterly revenue growth
    "rev_poor_pct": 0.0,         # flat/declining revenue
    "increase_score": 2,         # total score at/above this -> Increase
    "reduce_score": -2,          # total score at/below this -> Reduce
    "reference_benchmark": "NIFTY 50",
}


def merged(config=None):
    """RECO_CONFIG overlaid with any caller overrides."""
    return {**RECO_CONFIG, **(config or {})}


def criteria_text(config=None):
    """Human-readable list of the agent's rules (shown in the UI so the criteria
    can be reviewed and new ones requested)."""
    c = merged(config)
    return [
        f"Beat {c['reference_benchmark']} by ≥ {c['beat_margin_pct']:.0f}% on average "
        f"across the 3 shortest selected windows (short/medium term) → +1; lagged → −1.",
        f"Beat the whole portfolio by ≥ {c['beat_margin_pct']:.0f}% (avg, same "
        f"windows) → +1; lagged → −1.",
        f"Long-term CAGR ≥ {c['cagr_good_pct']:.0f}% → +1; ≤ {c['cagr_poor_pct']:.0f}% → −1.",
        f"Position weight > {c['max_weight_pct']:.0f}% of the portfolio → −1 "
        f"(trim for concentration risk).",
        f"(d) Medium-term price trend: above the 200-DMA with 50-DMA > 200-DMA "
        f"(uptrend) → +1; below both (downtrend) → −1.",
        f"(b) Quarterly revenue growth ≥ {c['rev_good_pct']:.0f}% YoY and not "
        f"decelerating → +1; ≤ {c['rev_poor_pct']:.0f}% YoY or decelerating → −1.",
        f"Total score ≥ {c['increase_score']} → Increase; ≤ {c['reduce_score']} "
        f"→ Reduce; otherwise No change.",
    ]
