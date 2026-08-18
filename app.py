"""
Portfolio web app (iteration 1)
Upload a CSV of holdings -> see per-stock + portfolio performance as a table.

Run:
    pip install flask yfinance pandas
    python app.py
    # open http://127.0.0.1:5000
"""

import io

import pandas as pd
from flask import Flask, request, render_template_string

import engine
import recommender

app = Flask(__name__)

# ---- number formatting helpers (passed into the template) ----

def fmt_money(x):
    return "n/a" if x is None or pd.isna(x) else f"{x:,.2f}"

def fmt_num(x):
    return "n/a" if x is None or pd.isna(x) else f"{x:,.2f}"

def fmt_pct(x):
    return "n/a" if x is None or pd.isna(x) else f"{x:+.2f}%"

def fmt_weight(x):
    return "n/a" if x is None or pd.isna(x) else f"{x:.1f}%"

def fmt_ret(x):
    # Blank (not "n/a") for period-return cells that don't apply — e.g. a window
    # longer than the holding period, or a period with no data.
    return "" if x is None or pd.isna(x) else f"{x:+.2f}%"

def sign_class(x):
    if x is None or pd.isna(x):
        return "neutral"
    return "pos" if x >= 0 else "neg"

def fmt_date(x):
    if x is None or pd.isna(x):
        return "n/a"
    try:
        return pd.Timestamp(x).strftime("%Y-%m-%d")
    except (ValueError, TypeError):
        return "n/a"


# ---- user-selectable return periods ----

N_PERIOD_SLOTS = 5
DEFAULT_PERIODS = ["1m", "3m", "6m", "1y", "3y"]
# (key, label) options for every dropdown, in catalog order.
PERIOD_OPTIONS = [(k, engine.PERIOD_LABELS[k]) for k in engine.TRAILING_PERIODS]


def read_slots(form):
    """Raw value chosen in each of the 5 dropdowns (falls back to the default)."""
    slots = []
    for i in range(N_PERIOD_SLOTS):
        v = form.get(f"period{i}")
        slots.append(v if v in engine.TRAILING_PERIODS else DEFAULT_PERIODS[i])
    return slots


def dedupe_periods(slots):
    """Order-preserving de-duplication -> the period columns actually shown."""
    seen = []
    for v in slots:
        if v not in seen:
            seen.append(v)
    return seen


# ---- relative-performance line chart (dependency-free inline SVG) ----

SERIES_COLORS = {
    "Portfolio": "#58a6ff",
    "NIFTY 50":  "#3fb950",
    "S&P 500":   "#d29922",
    "NASDAQ":    "#bc8cff",
}
_FALLBACK_COLORS = ["#58a6ff", "#3fb950", "#d29922", "#bc8cff", "#f85149", "#39c5cf"]


def render_chart_svg(comparison, width=900, height=360):
    """Build a themed, multi-series line chart (base-100 growth) as inline SVG.

    `comparison` is engine.comparison_series() output. Returns "" if there is
    nothing to plot.
    """
    dates = comparison.get("dates", [])
    series = comparison.get("series", {})
    if not dates or not series:
        return ""

    pad_l, pad_r, pad_t, pad_b = 52, 16, 40, 30
    plot_w, plot_h = width - pad_l - pad_r, height - pad_t - pad_b
    n = len(dates)

    vals = [v for ys in series.values() for v in ys if v is not None]
    if not vals:
        return ""
    ymin, ymax = min(vals), max(vals)
    if ymin == ymax:
        ymin, ymax = ymin - 1, ymax + 1
    span = ymax - ymin
    ymin, ymax = ymin - span * 0.05, ymax + span * 0.05

    def sx(i):
        return pad_l + (plot_w * i / (n - 1) if n > 1 else 0)

    def sy(v):
        return pad_t + plot_h * (1 - (v - ymin) / (ymax - ymin))

    parts = [f'<svg viewBox="0 0 {width} {height}" width="100%" '
             f'xmlns="http://www.w3.org/2000/svg" role="img" '
             f'aria-label="Relative performance chart" font-family="inherit">']

    # y gridlines + labels
    for frac in (0, 0.25, 0.5, 0.75, 1):
        val = ymin + (ymax - ymin) * frac
        yy = sy(val)
        parts.append(f'<line x1="{pad_l}" y1="{yy:.1f}" x2="{width - pad_r}" '
                     f'y2="{yy:.1f}" stroke="#2a3441" stroke-width="1"/>')
        parts.append(f'<text x="{pad_l - 8}" y="{yy + 3:.1f}" fill="#8b98a5" '
                     f'font-size="11" text-anchor="end">{val:.0f}</text>')

    # baseline at 100 (starting value) if within range
    if ymin <= 100 <= ymax:
        yb = sy(100)
        parts.append(f'<line x1="{pad_l}" y1="{yb:.1f}" x2="{width - pad_r}" '
                     f'y2="{yb:.1f}" stroke="#8b98a5" stroke-width="1" '
                     f'stroke-dasharray="4 4" opacity="0.5"/>')

    # x labels: first, middle, last
    for i in (0, n // 2, n - 1):
        parts.append(f'<text x="{sx(i):.1f}" y="{height - 8}" fill="#8b98a5" '
                     f'font-size="11" text-anchor="middle">{dates[i]}</text>')

    # series polylines
    for k, (label, ys) in enumerate(series.items()):
        color = SERIES_COLORS.get(label, _FALLBACK_COLORS[k % len(_FALLBACK_COLORS)])
        pts = " ".join(f"{sx(i):.1f},{sy(v):.1f}"
                       for i, v in enumerate(ys) if v is not None)
        width_stroke = 2.5 if label == "Portfolio" else 1.6
        parts.append(f'<polyline points="{pts}" fill="none" stroke="{color}" '
                     f'stroke-width="{width_stroke}" stroke-linejoin="round" '
                     f'stroke-linecap="round"/>')

    # legend across the top
    lx = pad_l
    for k, label in enumerate(series):
        color = SERIES_COLORS.get(label, _FALLBACK_COLORS[k % len(_FALLBACK_COLORS)])
        parts.append(f'<rect x="{lx}" y="14" width="12" height="12" rx="2" fill="{color}"/>')
        parts.append(f'<text x="{lx + 17}" y="24" fill="#e6edf3" font-size="12">{label}</text>')
        lx += 30 + len(label) * 8

    parts.append("</svg>")
    return "".join(parts)


PAGE = """
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Portfolio Performance</title>
<style>
  :root { --bg:#0f1419; --card:#1a212b; --line:#2a3441; --txt:#e6edf3;
          --muted:#8b98a5; --pos:#3fb950; --neg:#f85149; --accent:#58a6ff; }
  * { box-sizing: border-box; }
  body { margin:0; font:15px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
         background:var(--bg); color:var(--txt); padding:32px; }
  .wrap { max-width:1100px; margin:0 auto; }
  h1 { font-size:22px; margin:0 0 4px; }
  h2 { font-size:16px; margin:32px 0 4px; }
  .sub { color:var(--muted); margin:0 0 24px; font-size:14px; }
  h2 + .sub { margin-bottom:12px; }
  form { background:var(--card); border:1px solid var(--line); border-radius:10px;
         padding:18px; display:flex; gap:12px; align-items:center; flex-wrap:wrap; }
  input[type=file] { color:var(--muted); }
  .periods { display:flex; gap:10px; flex-wrap:wrap; }
  .periods label { display:flex; flex-direction:column; gap:4px; font-size:11px;
                   color:var(--muted); text-transform:uppercase; letter-spacing:.04em; }
  select { background:#0b0f14; color:var(--txt); border:1px solid var(--line);
           border-radius:6px; padding:7px 8px; font:inherit; cursor:pointer; }
  button { background:var(--accent); color:#04121f; border:0; border-radius:7px;
           padding:9px 18px; font-weight:600; cursor:pointer; }
  .err { background:#3d1c1c; border:1px solid var(--neg); color:#ffb3ad;
         padding:12px 16px; border-radius:8px; margin:20px 0; }
  .cards { display:grid; grid-template-columns:repeat(auto-fit,minmax(180px,1fr));
           gap:14px; margin:24px 0; }
  .card { background:var(--card); border:1px solid var(--line); border-radius:10px; padding:16px; }
  .card .label { color:var(--muted); font-size:12px; text-transform:uppercase; letter-spacing:.04em; }
  .card .val { font-size:22px; font-weight:650; margin-top:6px; }
  /* Base table (used as-is for the narrow benchmark table — no scrolling). */
  table { width:100%; border-collapse:collapse; margin-top:8px; font-variant-numeric:tabular-nums;
          background:var(--card); border:1px solid var(--line); border-radius:10px; overflow:hidden; }
  th,td { padding:10px 12px; text-align:right; white-space:nowrap; border-bottom:1px solid var(--line); }
  th { color:var(--muted); font-size:12px; text-transform:uppercase; letter-spacing:.03em; font-weight:600; }
  th:first-child, td:first-child { text-align:left; font-weight:600; }
  tbody tr:last-child td { border-bottom:0; }
  tbody tr:hover td { background:#212a35; }
  .pos { color:var(--pos); } .neg { color:var(--neg); } .neutral { color:var(--muted); }
  tbody tr.hl td { background:#1d2836; }
  tbody tr.hl td:first-child { color:var(--accent); }

  /* Excel-style freeze pane: only the Holdings table opts in via .tablewrap.
     Scroll happens inside this box; the header row and ticker column stay put. */
  .tablewrap { margin-top:8px; max-height:72vh; overflow:auto;
               border:1px solid var(--line); border-radius:10px; }
  .tablewrap table { margin:0; border:0; border-radius:0; }
  .tablewrap thead th { position:sticky; top:0; z-index:2; background:#141b24;
               box-shadow: inset 0 -1px 0 var(--line); }
  .tablewrap th:first-child, .tablewrap td:first-child { position:sticky; left:0; z-index:1;
               background:var(--card); box-shadow: inset -1px 0 0 var(--line); }
  .tablewrap thead th:first-child { z-index:3; background:#141b24; }
  .tablewrap tbody tr:hover td:first-child { background:#212a35; }
  .chart { padding:12px 16px; margin-top:8px; }
  .hint { color:var(--muted); font-size:13px; margin-top:18px; }
  code { background:#0b0f14; padding:2px 6px; border-radius:4px; }
  /* Analyze -> Recommendation navigation buttons */
  .navform { display:flex; justify-content:center; margin:28px 0 8px; }
  .navform button { font-size:15px; padding:11px 22px; }
  button.ghost { background:transparent; color:var(--accent); border:1px solid var(--line); }
</style>
</head>
<body>
<div class="wrap">
  <h1>Portfolio Performance</h1>
  <p class="sub">Upload a CSV with <b>ticker</b> and <b>shares</b> (required), plus optional <b>buy_price</b> and <b>buy_date</b>. Without buy prices, you get performance &amp; XIRR of your current holdings over the selected period vs the benchmarks.</p>

  <form method="post" enctype="multipart/form-data">
    <input type="file" name="file" accept=".csv" required>
    <div class="periods">
      {% for i in range(n_slots) %}
        <label>Period {{ i + 1 }}
          <select name="period{{ i }}">
            {% for key, lbl in period_options %}
              <option value="{{ key }}" {% if slots[i] == key %}selected{% endif %}>{{ lbl }}</option>
            {% endfor %}
          </select>
        </label>
      {% endfor %}
    </div>
    <button type="submit">Analyze</button>
  </form>

  {% if error %}<div class="err">{{ error }}</div>{% endif %}

  {% if summary %}
  {% if view == 'reco' %}
    {{ reco_html|safe }}
    <form method="post" action="/" class="navform">
      <textarea name="holdings" style="display:none">{{ holdings_csv }}</textarea>
      {% for i in range(n_slots) %}<input type="hidden" name="period{{ i }}" value="{{ slots[i] }}">{% endfor %}
      <button type="submit" class="ghost">&larr; Back to Analysis</button>
    </form>
  {% else %}
  <div id="screen-analysis">
    {% if mode == 'period' %}
    <div class="cards">
      <div class="card"><div class="label">Current Value</div><div class="val">{{ fmt_money(summary.total_value) }}</div></div>
      <div class="card"><div class="label">{{ headline_label }} Return</div>
        <div class="val {{ sign_class(bench_rows[0].returns[headline]) }}">{{ fmt_pct(bench_rows[0].returns[headline]) }}</div></div>
      <div class="card"><div class="label">Portfolio XIRR</div>
        <div class="val {{ sign_class(port_xirr) }}">{{ fmt_pct(port_xirr) }}</div></div>
      <div class="card"><div class="label">Holdings</div><div class="val">{{ summary.n_priced }}</div></div>
    </div>
    <p class="sub">No buy prices in the file — each holding is treated as bought at its listing (first-available) date and held to today. XIRR is money-weighted over that cash-flow stream.</p>
    {% else %}
    <div class="cards">
      <div class="card"><div class="label">Cost Basis</div><div class="val">{{ fmt_money(summary.total_cost) }}</div></div>
      <div class="card"><div class="label">Current Value</div><div class="val">{{ fmt_money(summary.total_value) }}</div></div>
      <div class="card"><div class="label">Absolute Return</div>
        <div class="val {{ sign_class(summary.total_return) }}">{{ fmt_money(summary.total_return) }} ({{ fmt_pct(summary.total_return_pct) }})</div></div>
      <div class="card"><div class="label">Portfolio XIRR</div>
        <div class="val {{ sign_class(port_xirr) }}">{{ fmt_pct(port_xirr) }}</div></div>
    </div>
    {% endif %}

    {% if summary.n_priced < summary.n_total %}
      <div class="err">Priced {{ summary.n_priced }} of {{ summary.n_total }} holdings. Rows without data show n/a (check ticker spelling / suffix like .NS).</div>
    {% endif %}

    {% if bench_rows %}
    <h2>Portfolio vs Benchmarks &mdash; Cumulative Return</h2>
    <p class="sub">Total price return over each window. Benchmarks: NIFTY 50, S&amp;P 500, Nasdaq Composite.</p>
    <table>
      <thead><tr>
        <th>Series</th>
        {% for p in periods %}<th>{{ period_labels[p] }}</th>{% endfor %}
      </tr></thead>
      <tbody>
      {% for b in bench_rows %}
        <tr {% if b.label == 'Portfolio' %}class="hl"{% endif %}>
          <td>{{ b.label }}</td>
          {% for p in periods %}
            <td class="{{ sign_class(b.returns[p]) }}">{{ fmt_pct(b.returns[p]) }}</td>
          {% endfor %}
        </tr>
      {% endfor %}
      </tbody>
    </table>

    {% if xirr_rows %}
    <h2>Portfolio vs Benchmarks &mdash; Money-weighted Return (XIRR)</h2>
    <p class="sub">A single annualized return over your actual cash-flow stream. Each benchmark uses the <b>same</b> amounts invested on the <b>same</b> dates &mdash; so this is a true like-for-like comparison when you invest over time.</p>
    <table>
      <thead><tr><th>Series</th><th>XIRR</th></tr></thead>
      <tbody>
      {% for x in xirr_rows %}
        <tr {% if x.label == 'Portfolio' %}class="hl"{% endif %}>
          <td>{{ x.label }}</td>
          <td class="{{ sign_class(x.xirr) }}">{{ fmt_pct(x.xirr) }}</td>
        </tr>
      {% endfor %}
      </tbody>
    </table>
    {% endif %}
    {% endif %}

    {% if chart_svg %}
    <h2>Relative Performance (last {{ chart_label }})</h2>
    <p class="sub">Growth of the current portfolio composition vs each index, rebased to 100 at the start.</p>
    <div class="card chart">{{ chart_svg | safe }}</div>
    {% endif %}

    <h2>Holdings</h2>
    <div class="tablewrap">
    <table>
      {% if mode == 'period' %}
      <thead><tr>
        <th>Ticker</th><th>Shares</th><th>Current</th><th>Value</th><th>Weight</th>
        {% for p in periods %}<th>{{ period_labels[p] }}</th>{% endfor %}
        <th>CAGR (listing)</th>
      </tr></thead>
      <tbody>
      {% for r in rows %}
        <tr>
          <td>{{ r.ticker }}</td>
          <td>{{ fmt_num(r.shares) }}</td>
          <td>{{ fmt_money(r.current_price) }}</td>
          <td>{{ fmt_money(r.current_value) }}</td>
          <td>{{ fmt_weight(r.weight_pct) }}</td>
          {% for p in periods %}
            <td class="{{ sign_class(r.returns[p]) }}">{{ fmt_ret(r.returns[p]) }}</td>
          {% endfor %}
          <td class="{{ sign_class(holding_cagr[r.ticker]) }}">{{ fmt_pct(holding_cagr[r.ticker]) }}</td>
        </tr>
      {% endfor %}
      </tbody>
      {% else %}
      <thead><tr>
        <th>Ticker</th><th>Shares</th><th>Buy Date</th><th>Buy Price</th><th>Current</th>
        <th>Cost Basis</th><th>Value</th><th>Abs Return</th><th>Abs %</th>
        {% for p in periods %}<th>{{ period_labels[p] }}</th>{% endfor %}
        <th>Years</th><th>CAGR</th>
      </tr></thead>
      <tbody>
      {% for r in rows %}
        <tr>
          <td>{{ r.ticker }}</td>
          <td>{{ fmt_num(r.shares) }}</td>
          <td>{{ fmt_date(r.buy_date) }}</td>
          <td>{{ fmt_money(r.buy_price) }}</td>
          <td>{{ fmt_money(r.current_price) }}</td>
          <td>{{ fmt_money(r.cost_basis) }}</td>
          <td>{{ fmt_money(r.current_value) }}</td>
          <td class="{{ sign_class(r.abs_return) }}">{{ fmt_money(r.abs_return) }}</td>
          <td class="{{ sign_class(r.abs_return_pct) }}">{{ fmt_pct(r.abs_return_pct) }}</td>
          {% for p in periods %}
            <td class="{{ sign_class(r.returns[p]) }}">{{ fmt_ret(r.returns[p]) }}</td>
          {% endfor %}
          <td>{{ fmt_num(r.years_held) }}</td>
          <td class="{{ sign_class(r.cagr_pct) }}">{{ fmt_pct(r.cagr_pct) }}</td>
        </tr>
      {% endfor %}
      </tbody>
      {% endif %}
    </table>
    </div>
    <p class="hint">Prices are split/dividend-adjusted. Period columns are the stock's trailing price returns; for a holding with a buy date, windows longer than your holding period are left blank (they predate ownership). The last column is each holding's <b>CAGR</b> (annualized, a year or more) &mdash; from your buy_date in cost-basis mode, or from the stock's listing (first-available) date when no buy price is given. The portfolio-level <b>XIRR</b> above is money-weighted over your whole cash-flow stream. Scroll the table sideways to see every column; the ticker column stays pinned.</p>
  </div><!-- /screen-analysis -->

  <form method="post" action="/recommendation" class="navform">
    <textarea name="holdings" style="display:none">{{ holdings_csv }}</textarea>
    {% for i in range(n_slots) %}<input type="hidden" name="period{{ i }}" value="{{ slots[i] }}">{% endfor %}
    <button type="submit">🎯 Get Recommendation</button>
  </form>
  {% endif %}{# /view #}
  {% endif %}{# /summary #}
</div>
</body>
</html>
"""


def render(slots=None, periods=None, rows=None, summary=None, error=None,
           bench_rows=None, chart_svg=None, chart_label=None,
           mode="cost", headline=None, headline_label=None, xirr_rows=None,
           port_xirr=None, holding_cagr=None, reco_html=None,
           view="analysis", holdings_csv=None):
    slots = slots or list(DEFAULT_PERIODS)
    periods = periods or dedupe_periods(slots)
    return render_template_string(
        PAGE, slots=slots, periods=periods, n_slots=N_PERIOD_SLOTS,
        period_options=PERIOD_OPTIONS, period_labels=engine.PERIOD_LABELS,
        rows=rows, summary=summary, error=error,
        bench_rows=bench_rows, chart_svg=chart_svg, chart_label=chart_label,
        mode=mode, headline=headline, headline_label=headline_label,
        xirr_rows=xirr_rows or [], port_xirr=port_xirr,
        holding_cagr=holding_cagr or {}, reco_html=reco_html,
        view=view, holdings_csv=holdings_csv,
        fmt_money=fmt_money, fmt_num=fmt_num, fmt_pct=fmt_pct,
        fmt_weight=fmt_weight, fmt_ret=fmt_ret, fmt_date=fmt_date, sign_class=sign_class,
    )


def load_holdings(req):
    """Normalized holdings DataFrame from an uploaded file, or from the embedded
    `holdings` CSV carried between the Analysis and Recommendation views."""
    file = req.files.get("file")
    if file and file.filename:
        raw = pd.read_csv(io.BytesIO(file.read()))
    else:
        text = req.form.get("holdings", "")
        if not text.strip():
            return None
        raw = pd.read_csv(io.StringIO(text))
    return engine.load_portfolio_df(raw)


def compute_analysis(df, slots):
    """Run the full analysis for a holdings DataFrame. Returns the render kwargs
    for the analysis view, plus `result`/`bench_rows`/`cagr_by_ticker` that the
    recommendation step reuses. Shared by the Analyze and Recommendation routes."""
    periods = dedupe_periods(slots)
    hist_period = engine.history_period_for(periods)
    holding_history = engine.fetch_history(df["ticker"].unique().tolist(),
                                           period=hist_period)
    prices = engine.prices_from_history(holding_history)
    returns = engine.trailing_returns_from_history(holding_history, periods)
    result = engine.compute_metrics(df, prices, returns, periods)
    summary = engine.portfolio_summary(result)
    rows = result.to_dict(orient="records")
    mode = "cost" if engine.has_cost_basis(df) else "period"

    benchmark_history = engine.fetch_benchmarks(period=hist_period)
    bench_rows = engine.benchmark_summary(df, holding_history, benchmark_history,
                                          prices, periods)
    window_days = max(engine.TRAILING_PERIODS[k] for k in periods)
    comparison = engine.comparison_series(df, holding_history, benchmark_history,
                                          window_days=window_days)
    chart_svg = render_chart_svg(comparison)
    headline = max(periods, key=lambda k: engine.TRAILING_PERIODS[k])
    xirr_rows = engine.xirr_comparison(df, result, holding_history,
                                       benchmark_history, prices, mode)
    holding_cagr = ({t: engine.stock_cagr_from_listing(holding_history.get(t),
                     prices.get(t)) for t in df["ticker"].unique()}
                    if mode == "period" else {})
    cagr_by_ticker = holding_cagr if mode == "period" else {
        r["ticker"]: (None if pd.isna(r["cagr_pct"]) else r["cagr_pct"]) for r in rows}

    render_kwargs = dict(
        periods=periods, rows=rows, summary=summary, mode=mode, bench_rows=bench_rows,
        chart_svg=chart_svg, chart_label=engine.PERIOD_LABELS[headline],
        headline=headline, headline_label=engine.PERIOD_LABELS[headline],
        xirr_rows=xirr_rows, port_xirr=xirr_rows[0]["xirr"], holding_cagr=holding_cagr,
        holdings_csv=df.to_csv(index=False),
    )
    return render_kwargs, result, bench_rows, cagr_by_ticker, holding_history


@app.route("/", methods=["GET", "POST"])
def index():
    """Analyze: upload a CSV (or re-run from embedded holdings) -> analysis view."""
    if request.method == "GET":
        return render()
    slots = read_slots(request.form)
    try:
        df = load_holdings(request)
        if df is None:
            return render(slots=slots, error="No file selected.")
        if df.empty:
            return render(slots=slots, error="No valid rows found after parsing the CSV.")
        kwargs, _result, _bench, _cagr, _hist = compute_analysis(df, slots)
        return render(slots=slots, view="analysis", **kwargs)
    except Exception as e:
        return render(slots=slots, error=f"Could not process file: {e}")


@app.route("/recommendation", methods=["POST"])
def recommendation():
    """Recommendation: runs on demand from the analysis view's holdings, then
    renders the recommendation screen (a separate step from Analyze)."""
    slots = read_slots(request.form)
    try:
        df = load_holdings(request)
        if df is None or df.empty:
            return render(slots=slots,
                          error="Run an analysis first, then request a recommendation.")
        kwargs, result, bench_rows, cagr_by_ticker, holding_history = compute_analysis(df, slots)
        # (d) technicals from the price history in hand + (b) revenue via a
        # yfinance fetch — the extra fetch is why this runs on demand, not in Analyze.
        signals = recommender.gather_signals(df, holding_history)
        recos = recommender.recommend_portfolio(result, bench_rows, kwargs["periods"],
                                                cagr_by_ticker, signals=signals)
        reco_html = recommender.render_reco_screen(
            recos, recommender.summarize(recos), recommender.criteria_text())
        return render(slots=slots, view="reco", periods=kwargs["periods"],
                      summary=kwargs["summary"], holdings_csv=kwargs["holdings_csv"],
                      reco_html=reco_html)
    except Exception as e:
        return render(slots=slots, error=f"Could not generate recommendation: {e}")


if __name__ == "__main__":
    app.run(debug=True, port=5000)
