"""Modular, rule-based portfolio recommendation agent (v1).

Imported by the web app; imports `engine` read-only. Public surface:
    recommend_portfolio(result, bench_rows, periods, cagr_by_ticker) -> [reco, ...]
    summarize(recos) -> {"Increase": n, "No change": n, "Reduce": n}
    criteria_text() -> [str, ...]      # the agent's rules, for display
    render_reco_screen(recos, counts, criteria) -> html fragment
"""
from .core import recommend_portfolio, summarize
from .config import RECO_CONFIG, criteria_text
from .render import render_reco_screen
from .signals import gather_signals

__all__ = [
    "recommend_portfolio", "summarize", "RECO_CONFIG",
    "criteria_text", "render_reco_screen", "gather_signals",
]
