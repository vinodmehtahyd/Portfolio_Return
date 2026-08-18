"""Render the recommendation screen as a self-contained HTML fragment.

The app drops this into the page via {{ reco_html|safe }}, so the main template
stays tiny. Styles here are scoped under .reco-scr; it reuses the page's CSS
variables and generic .card/.cards/table classes for a consistent look.
"""
import jinja2

import engine


def _fmt_pct(x):
    return "n/a" if x is None else f"{x:+.2f}%"


def _fmt_weight(x):
    return "n/a" if x is None else f"{x:.1f}%"


def _fmt_delta(x):
    if x is None or abs(x) < 0.05:
        return "—"
    return f"Add ~{x:.1f}%" if x > 0 else f"Trim ~{abs(x):.1f}%"


def _action_class(a):
    return {"Increase": "pos", "Reduce": "neg"}.get(a, "neutral")


def _trend_class(t):
    return {"Uptrend": "pos", "Downtrend": "neg"}.get(t, "neutral")


def _fmt_rev(fund):
    yoy = (fund or {}).get("rev_yoy_pct")
    if yoy is None:
        return "n/a", "neutral"
    trend = (fund or {}).get("rev_trend")
    arrow = {"Accelerating": " ↑", "Decelerating": " ↓"}.get(trend, "")
    cls = "pos" if yoy >= 0 else "neg"
    return f"{yoy:+.0f}%{arrow}", cls


_TEMPLATE = """
<style>
  .reco-scr .reco th, .reco-scr .reco td { text-align:left; white-space:normal; }
  .reco-scr .why div { color:var(--muted); font-size:13px; }
  .reco-scr .badge { display:inline-block; padding:3px 10px; border-radius:20px;
                     font-size:12px; font-weight:700; }
  .reco-scr .badge.pos { background:rgba(63,185,80,.16); color:var(--pos); }
  .reco-scr .badge.neg { background:rgba(248,81,73,.16); color:var(--neg); }
  .reco-scr .badge.neutral { background:#232c37; color:var(--muted); }
  .reco-scr .criteria { margin-top:16px; }
  .reco-scr .criteria ul { margin:10px 0 0; padding-left:20px; }
  .reco-scr .criteria li { margin:5px 0; color:var(--muted); font-size:13px; }
</style>
<div class="reco-scr">
  <h2>Agent Recommendations</h2>
  <p class="sub">Rule-based signals to rebalance toward outperformance &mdash; trim
  laggards, add to leaders, respect concentration limits.
  <b>Informational only, not investment advice.</b></p>

  <div class="cards">
    <div class="card"><div class="label">Increase</div><div class="val pos">{{ counts.Increase }}</div></div>
    <div class="card"><div class="label">No change</div><div class="val neutral">{{ counts['No change'] }}</div></div>
    <div class="card"><div class="label">Reduce</div><div class="val neg">{{ counts.Reduce }}</div></div>
  </div>

  <table class="reco">
    <thead><tr>
      <th>Ticker</th><th>Weight</th><th>Action</th><th>Suggested</th><th>Basis</th>
      <th>Trend</th><th>Rev YoY</th><th>Why</th>
    </tr></thead>
    <tbody>
    {% for x in recos %}
      {% set rev = fmt_rev(x.fund) %}
      <tr>
        <td><b>{{ x.ticker }}</b></td>
        <td>{{ fmt_weight(x.weight_pct) }}</td>
        <td><span class="badge {{ action_class(x.action) }}">{{ x.action }}</span></td>
        <td class="{{ action_class(x.action) }}">{{ fmt_delta(x.suggested_delta) }}</td>
        <td>{% if x.stock_short is not none %}{{ x.short_label }} avg {{ fmt_pct(x.stock_short) }}{% if x.rel_bench is not none %} &middot; {{ x.reference }} {{ '%+.1f'|format(x.rel_bench) }}%{% endif %}{% else %}n/a{% endif %}</td>
        <td class="{{ trend_class(x.tech.get('trend')) }}">{{ x.tech.get('trend') or 'n/a' }}</td>
        <td class="{{ rev[1] }}">{{ rev[0] }}</td>
        <td class="why">{% for reason in x.reasons %}<div>{{ reason }}</div>{% endfor %}</td>
      </tr>
    {% endfor %}
    </tbody>
  </table>

  <div class="card criteria">
    <div class="label">Agent criteria &mdash; review &amp; tell me what to add or change</div>
    <ul>{% for c in criteria %}<li>{{ c }}</li>{% endfor %}</ul>
  </div>
</div>
"""


# Compiled once. Autoescape so recommendation text is HTML-safe; decoupled from
# Flask (no app context needed) since this is a standalone module.
_TMPL = jinja2.Environment(autoescape=True).from_string(_TEMPLATE)


def render_reco_screen(recos, counts, criteria):
    """HTML fragment for the recommendation screen."""
    return _TMPL.render(
        recos=recos, counts=counts, criteria=criteria,
        period_labels=engine.PERIOD_LABELS, fmt_pct=_fmt_pct,
        fmt_weight=_fmt_weight, fmt_delta=_fmt_delta, action_class=_action_class,
        trend_class=_trend_class, fmt_rev=_fmt_rev,
    )
