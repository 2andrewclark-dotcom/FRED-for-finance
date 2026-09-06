"""
FRED Interest Rate Dashboard — light, broadsheet theme
----------------------------------------------------
Live macro/rates data from the FRED API, styled as a crisp, print-inspired
dashboard: white background, Times New Roman, hairline borders, zero
border-radius. Built out for an economics/finance audience with a broader
set of policy, curve, credit, inflation, labor and liquidity series, NBER
recession shading, a correlation matrix, and richer summary statistics.

Tabs:
  - Dashboard: a fixed "At A Glance" macro strip, category-grouped KPI
               cards w/ sparklines, a yield-curve gauge, a configurable
               rate-trend chart, a scrolling data-highlights ticker, and
               upcoming FRED release dates.
  - Historical Comparison & Analysis: overlay multiple series, normalize,
               shade NBER recessions, view a correlation matrix, and see
               richer summary statistics (52W range, z-score, percentile).
  - Export: download the selected rates/date-range as CSV or Excel.

Run with:  streamlit run app.py
Requires a free FRED API key: https://fred.stlouisfed.org/docs/api/api_key.html
Put the included .streamlit/config.toml next to app.py so the native
Streamlit widgets (sidebar, inputs, tables) also pick up the light theme.
"""

import io
import os
from datetime import date, datetime, timedelta

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import requests
import streamlit as st

try:
    from streamlit_autorefresh import st_autorefresh
    HAS_AUTOREFRESH = True
except ImportError:
    HAS_AUTOREFRESH = False

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
st.set_page_config(page_title="FRED Rate Dashboard", layout="wide")

FRED_BASE = "https://api.stlouisfed.org/fred"

# Each series carries: FRED series id, a display category, the FRED "units"
# transform to request (lin = level, pc1 = percent change from a year ago),
# a display suffix, decimal places, and an optional display-scale multiplier.
RATE_SERIES = {
    # -- Policy & money-market rates --------------------------------------
    "Effective Fed Funds Rate":     {"id": "FEDFUNDS", "cat": "Policy & Money Market", "units": "lin", "suffix": "%", "dp": 2},
    "Fed Funds Rate (Daily)":       {"id": "DFF",      "cat": "Policy & Money Market", "units": "lin", "suffix": "%", "dp": 2},
    "SOFR":                         {"id": "SOFR",     "cat": "Policy & Money Market", "units": "lin", "suffix": "%", "dp": 2},
    "IORB (Interest on Reserves)":  {"id": "IORB",     "cat": "Policy & Money Market", "units": "lin", "suffix": "%", "dp": 2},
    # -- Treasury yield curve ----------------------------------------------
    "1-Month Treasury":  {"id": "DGS1MO", "cat": "Treasury Yield Curve", "units": "lin", "suffix": "%", "dp": 2},
    "3-Month Treasury":  {"id": "DGS3MO", "cat": "Treasury Yield Curve", "units": "lin", "suffix": "%", "dp": 2},
    "6-Month Treasury":  {"id": "DGS6MO", "cat": "Treasury Yield Curve", "units": "lin", "suffix": "%", "dp": 2},
    "1-Year Treasury":   {"id": "DGS1",   "cat": "Treasury Yield Curve", "units": "lin", "suffix": "%", "dp": 2},
    "2-Year Treasury":   {"id": "DGS2",   "cat": "Treasury Yield Curve", "units": "lin", "suffix": "%", "dp": 2},
    "5-Year Treasury":   {"id": "DGS5",   "cat": "Treasury Yield Curve", "units": "lin", "suffix": "%", "dp": 2},
    "10-Year Treasury":  {"id": "DGS10",  "cat": "Treasury Yield Curve", "units": "lin", "suffix": "%", "dp": 2},
    "30-Year Treasury":  {"id": "DGS30",  "cat": "Treasury Yield Curve", "units": "lin", "suffix": "%", "dp": 2},
    # -- Yield curve spreads -------------------------------------------------
    "10Y-2Y Treasury Spread": {"id": "T10Y2Y", "cat": "Yield Curve Spreads", "units": "lin", "suffix": "%", "dp": 2},
    "10Y-3M Treasury Spread": {"id": "T10Y3M", "cat": "Yield Curve Spreads", "units": "lin", "suffix": "%", "dp": 2},
    # -- Inflation & expectations ---------------------------------------
    "CPI, YoY":                {"id": "CPIAUCSL", "cat": "Inflation & Expectations", "units": "pc1", "suffix": "%", "dp": 2},
    "Core CPI, YoY":           {"id": "CPILFESL", "cat": "Inflation & Expectations", "units": "pc1", "suffix": "%", "dp": 2},
    "PCE Price Index, YoY":    {"id": "PCEPI",    "cat": "Inflation & Expectations", "units": "pc1", "suffix": "%", "dp": 2},
    "10Y Breakeven Inflation": {"id": "T10YIE",   "cat": "Inflation & Expectations", "units": "lin", "suffix": "%", "dp": 2},
    "5Y Breakeven Inflation":  {"id": "T5YIE",    "cat": "Inflation & Expectations", "units": "lin", "suffix": "%", "dp": 2},
    # -- Credit markets -------------------------------------------------------
    "AAA Corporate Bond Yield": {"id": "AAA",          "cat": "Credit Markets", "units": "lin", "suffix": "%", "dp": 2},
    "BAA Corporate Bond Yield": {"id": "BAA",          "cat": "Credit Markets", "units": "lin", "suffix": "%", "dp": 2},
    "Aaa - 10Y Treasury Spread": {"id": "AAA10Y",      "cat": "Credit Markets", "units": "lin", "suffix": "%", "dp": 2},
    "High-Yield OAS":           {"id": "BAMLH0A0HYM2", "cat": "Credit Markets", "units": "lin", "suffix": "%", "dp": 2},
    "Investment-Grade OAS":     {"id": "BAMLC0A0CM",   "cat": "Credit Markets", "units": "lin", "suffix": "%", "dp": 2},
    # -- Labor & growth ------------------------------------------------------
    "Unemployment Rate":      {"id": "UNRATE",           "cat": "Labor & Growth", "units": "lin", "suffix": "%", "dp": 1},
    "Real GDP Growth (SAAR)": {"id": "A191RL1Q225SBEA", "cat": "Labor & Growth", "units": "lin", "suffix": "%", "dp": 1},
    # -- Consumer & bank lending ------------------------------------------
    "30-Year Fixed Mortgage": {"id": "MORTGAGE30US", "cat": "Consumer & Bank Lending", "units": "lin", "suffix": "%", "dp": 2},
    "15-Year Fixed Mortgage": {"id": "MORTGAGE15US", "cat": "Consumer & Bank Lending", "units": "lin", "suffix": "%", "dp": 2},
    "Bank Prime Loan Rate":   {"id": "DPRIME",       "cat": "Consumer & Bank Lending", "units": "lin", "suffix": "%", "dp": 2},
    # -- Monetary & liquidity -----------------------------------------------
    "M2 Money Supply, YoY":             {"id": "M2SL", "cat": "Monetary & Liquidity", "units": "pc1", "suffix": "%", "dp": 2},
    "Fed Balance Sheet (Total Assets)": {"id": "WALCL", "cat": "Monetary & Liquidity", "units": "lin", "suffix": " $T", "dp": 2, "scale": 1e-6},
}

# Series pinned at the top of the Dashboard tab regardless of sidebar picks.
HEADLINE_NAMES = [
    "Effective Fed Funds Rate",
    "10-Year Treasury",
    "10Y-2Y Treasury Spread",
    "CPI, YoY",
    "Unemployment Rate",
]

DEFAULT_RATES = list(RATE_SERIES.keys())

CATEGORY_ORDER = [
    "Policy & Money Market",
    "Treasury Yield Curve",
    "Yield Curve Spreads",
    "Inflation & Expectations",
    "Credit Markets",
    "Labor & Growth",
    "Consumer & Bank Lending",
    "Monetary & Liquidity",
]

CATEGORY_COLORS = {
    "Policy & Money Market": "#1a3a6b",
    "Treasury Yield Curve": "#1a5c38",
    "Yield Curve Spreads": "#6b3a1a",
    "Inflation & Expectations": "#8a6d1a",
    "Credit Markets": "#5c1a5c",
    "Labor & Growth": "#8a1a1a",
    "Consumer & Bank Lending": "#1a5c5c",
    "Monetary & Liquidity": "#3a3a3a",
}

RELEASE_KEYWORDS = [
    "interest rate", "h.15", "selected interest",
    "consumer price index", "producer price index",
    "employment situation", "employment cost",
    "gross domestic product", "personal income",
    "beige book", "flow of funds", "money stock", "h.6", "h.4.1",
    "federal open market", "fomc", "consumer sentiment",
]

PRESET_RANGES = ["1M", "3M", "6M", "YTD", "1Y", "5Y", "10Y", "Max", "Custom"]

# 13 saturated, print-legible colors for multi-line charts on a white page.
CHART_PALETTE = [
    "#1a3a6b", "#8a1a1a", "#1a5c38", "#8a6d1a", "#5c1a5c",
    "#1a5c5c", "#6b3a1a", "#3a3a3a", "#a0522d", "#4b0082",
    "#006064", "#827717", "#37474f",
]

APP_CSS = """
<style>
.stApp, .stApp * {
  font-family: 'Times New Roman', Times, Georgia, serif !important;
}
* { border-radius: 0 !important; }
#MainMenu {visibility: hidden;}
footer {visibility: hidden;}

.stApp { background-color: #ffffff; }

.brand-dots span { display:inline-block; width:9px; height:9px; margin-right:5px; }
.dot-navy{background:#1a3a6b;} .dot-crimson{background:#8a1a1a;} .dot-forest{background:#1a5c38;} .dot-grey{background:#4b5163;}

.live-dot { display:inline-block; width:8px; height:8px; background:#1a5c38;
  margin-right:6px; animation: pulse 2s infinite; }
@keyframes pulse {
  0% { box-shadow: 0 0 0 0 rgba(26,92,56,0.55); }
  70% { box-shadow: 0 0 0 8px rgba(26,92,56,0); }
  100% { box-shadow: 0 0 0 0 rgba(26,92,56,0); }
}

.ticker-wrap { width:100%; overflow:hidden; background:#f5f5f0; border:1px solid #111111;
  padding:9px 0; margin: 6px 0 18px 0; }
.ticker { display:inline-block; white-space:nowrap; padding-left:100%; animation: ticker 42s linear infinite; }
.ticker:hover { animation-play-state: paused; }
.ticker span { display:inline-block; padding:0 2.2rem; color:#333333; font-size:14px; }
.ticker span strong { color:#000000; }
@keyframes ticker { 0% { transform:translate(0,0);} 100% { transform:translate(-50%,0);} }

.row-bar { height:2px; margin:2px 0 12px 0; }

.cat-header { font-size:13px; font-weight:700; letter-spacing:0.6px; text-transform:uppercase;
  color:#111111; margin: 20px 0 8px 0; border-bottom:2px solid #111111; padding-bottom:5px; }

.kpi-card { background:#ffffff; border:1px solid #111111; padding:14px 16px 10px 16px;
  margin-bottom:6px; min-height:188px; }
.kpi-card--headline { border-width:2px; min-height:196px; }
.kpi-label { color:#333333; font-size:13px; font-weight:600; margin-bottom:8px; }
.kpi-value { font-size:26px; font-weight:700; margin-bottom:10px; line-height:1; color:#111111; }
.kpi-card--headline .kpi-value { font-size:32px; }
.kpi-compare { display:flex; justify-content:space-between; gap:10px; margin-bottom:8px;
  border-top:1px solid #dddddd; padding-top:8px; }
.kpi-compare-item { flex:1; }
.kpi-compare-label { color:#666666; font-size:10.5px; margin-bottom:2px; letter-spacing:0.2px; }
.kpi-up { color:#1a5c38; font-weight:700; font-size:13px; }
.kpi-down { color:#8a1a1a; font-weight:700; font-size:13px; }
.kpi-flat { color:#666666; font-weight:700; font-size:13px; }
.kpi-spark { margin-top:4px; line-height:0; }
.kpi-meta { color:#666666; font-size:11px; margin-top:8px; border-top:1px dotted #cccccc; padding-top:6px; }

.section-gap { margin-top: 8px; }
hr { border-color:#111111 !important; }
</style>
"""

# ---------------------------------------------------------------------------
# Data access (cached)
# ---------------------------------------------------------------------------
@st.cache_data(ttl=3600, show_spinner=False)
def fetch_series(series_id: str, api_key: str, start: str, end: str,
                  units: str = "lin", scale: float = 1.0) -> pd.DataFrame:
    url = f"{FRED_BASE}/series/observations"
    params = {
        "series_id": series_id, "api_key": api_key, "file_type": "json",
        "observation_start": start, "observation_end": end, "units": units,
    }
    r = requests.get(url, params=params, timeout=20)
    r.raise_for_status()
    obs = r.json().get("observations", [])
    df = pd.DataFrame(obs)
    if df.empty:
        return pd.DataFrame(columns=["date", "value"])
    df["date"] = pd.to_datetime(df["date"])
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    df = df[["date", "value"]].dropna().sort_values("date").reset_index(drop=True)
    if scale != 1.0:
        df["value"] = df["value"] * scale
    return df


@st.cache_data(ttl=3600, show_spinner="Fetching data from FRED...")
def load_selected_data(names: tuple, start: str, end: str, api_key: str) -> dict:
    result = {}
    for name in names:
        meta = RATE_SERIES[name]
        result[name] = fetch_series(
            meta["id"], api_key, start, end,
            units=meta.get("units", "lin"), scale=meta.get("scale", 1.0),
        )
    return result


@st.cache_data(ttl=86400, show_spinner=False)
def fetch_recession_bands(api_key: str, start: str, end: str):
    """NBER recession indicator (USREC) collapsed into (start, end) date bands."""
    df = fetch_series("USREC", api_key, start, end, units="lin")
    if df.empty:
        return []
    bands = []
    in_rec = False
    band_start = None
    for _, row in df.iterrows():
        if row["value"] >= 0.5 and not in_rec:
            in_rec = True
            band_start = row["date"]
        elif row["value"] < 0.5 and in_rec:
            in_rec = False
            bands.append((band_start, row["date"]))
    if in_rec:
        bands.append((band_start, df["date"].iloc[-1]))
    return bands


@st.cache_data(ttl=1800, show_spinner=False)
def fetch_upcoming_releases(api_key: str, days_ahead: int = 30) -> pd.DataFrame:
    today = date.today()
    url = f"{FRED_BASE}/releases/dates"
    params = {
        "api_key": api_key, "file_type": "json",
        "realtime_start": today.isoformat(),
        "realtime_end": (today + timedelta(days=days_ahead)).isoformat(),
        "include_release_dates_with_no_data": "true",
        "sort_order": "asc", "limit": 1000,
    }
    r = requests.get(url, params=params, timeout=20)
    r.raise_for_status()
    df = pd.DataFrame(r.json().get("release_dates", []))
    if df.empty:
        return df
    df["date"] = pd.to_datetime(df["date"])
    return df


def filter_relevant_releases(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    mask = df["release_name"].str.lower().apply(lambda n: any(k in n for k in RELEASE_KEYWORDS))
    return df[mask].sort_values("date")


def latest_and_delta(df: pd.DataFrame, year_lookback_days: int = 365):
    """Returns (latest_value, delta_vs_prior_reading, delta_vs_year_ago, latest_date)."""
    if df.empty or len(df) < 2:
        return None, None, None, None
    latest_row = df.iloc[-1]
    latest_val, latest_date = latest_row["value"], latest_row["date"]
    prior_val = df.iloc[-2]["value"]
    cutoff = latest_date - pd.Timedelta(days=year_lookback_days)
    prior_year_df = df[df["date"] <= cutoff]
    prior_year_val = prior_year_df.iloc[-1]["value"] if not prior_year_df.empty else df.iloc[0]["value"]
    return latest_val, latest_val - prior_val, latest_val - prior_year_val, latest_date


def get_default_api_key() -> str:
    try:
        return st.secrets["FRED_API_KEY"]
    except Exception:
        return os.environ.get("FRED_API_KEY", "")


# ---------------------------------------------------------------------------
# Dynamic-component helpers
# ---------------------------------------------------------------------------
def sparkline_svg(values, color="#1a3a6b", width=180, height=40) -> str:
    """Build a small inline SVG sparkline (line + soft fill) from raw values."""
    values = [v for v in values if pd.notna(v)]
    if len(values) < 2:
        return ""
    vmin, vmax = min(values), max(values)
    rng = (vmax - vmin) or 1
    n = len(values)
    step = width / (n - 1)
    pts = []
    for i, v in enumerate(values):
        x = i * step
        y = height - ((v - vmin) / rng) * (height - 6) - 3
        pts.append((x, y))
    path = " ".join(f"{'L' if i else 'M'}{x:.1f},{y:.1f}" for i, (x, y) in enumerate(pts))
    fill_path = (
        f'<path d="{path} L{pts[-1][0]:.1f},{height} L0,{height} Z" '
        f'fill="{color}" fill-opacity="0.12" stroke="none"/>'
    )
    return (
        f'<svg width="100%" height="{height}" viewBox="0 0 {width} {height}" '
        f'preserveAspectRatio="none" xmlns="http://www.w3.org/2000/svg">'
        f'{fill_path}'
        f'<path d="{path}" fill="none" stroke="{color}" stroke-width="2.2" '
        f'stroke-linecap="round" stroke-linejoin="round"/></svg>'
    )


def fmt_delta(d, dp=2, suffix="%"):
    if d is None:
        return "—", "kpi-flat"
    if d > 0:
        return f"▲ {abs(d):.{dp}f}{suffix}", "kpi-up"
    if d < 0:
        return f"▼ {abs(d):.{dp}f}{suffix}", "kpi-down"
    return f"• 0.00{suffix}", "kpi-flat"


def render_kpi_card(name: str, df: pd.DataFrame, accent: str, meta: dict, headline: bool = False):
    suffix = meta.get("suffix", "%")
    dp = meta.get("dp", 2)
    card_class = "kpi-card kpi-card--headline" if headline else "kpi-card"
    if df.empty or len(df) < 2:
        st.markdown(
            f"<div class='{card_class}'><div class='kpi-label'>{name}</div>"
            f"<div class='kpi-value' style='color:{accent};'>N/A</div></div>",
            unsafe_allow_html=True,
        )
        return
    latest_val, prior_delta, year_delta, latest_date = latest_and_delta(df)
    p_text, p_cls = fmt_delta(prior_delta, dp, suffix)
    y_text, y_cls = fmt_delta(year_delta, dp, suffix)
    spark = sparkline_svg(df["value"].tail(60).tolist(), color=accent)

    window_365 = df[df["date"] >= (latest_date - pd.Timedelta(days=365))]
    if not window_365.empty:
        range_txt = (
            f"52W range {window_365['value'].min():.{dp}f}{suffix} "
            f"to {window_365['value'].max():.{dp}f}{suffix}"
        )
    else:
        range_txt = ""

    html = f"""
    <div class="{card_class}">
      <div class="kpi-label">{name}</div>
      <div class="kpi-value" style="color:{accent};">{latest_val:.{dp}f}{suffix}</div>
      <div class="kpi-compare">
        <div class="kpi-compare-item">
          <div class="kpi-compare-label">PRIOR READING</div>
          <div class="{p_cls}">{p_text}</div>
        </div>
        <div class="kpi-compare-item">
          <div class="kpi-compare-label">YEAR AGO</div>
          <div class="{y_cls}">{y_text}</div>
        </div>
      </div>
      <div class="kpi-spark">{spark}</div>
      <div class="kpi-meta">As of {latest_date:%b %d, %Y} &nbsp;/&nbsp; {meta['id']}<br/>{range_txt}</div>
    </div>
    """
    st.markdown(html, unsafe_allow_html=True)


def render_kpi_grid(names, data):
    if not names:
        return
    grouped = {}
    for n in names:
        grouped.setdefault(RATE_SERIES[n]["cat"], []).append(n)
    for cat in CATEGORY_ORDER:
        if cat not in grouped:
            continue
        color = CATEGORY_COLORS.get(cat, "#111111")
        st.markdown(
            f"<div class='cat-header' style='border-bottom-color:{color};'>{cat}</div>",
            unsafe_allow_html=True,
        )
        cat_names = grouped[cat]
        rows = [cat_names[i:i + 4] for i in range(0, len(cat_names), 4)]
        for row_names in rows:
            cols = st.columns(len(row_names))
            for col, name in zip(cols, row_names):
                with col:
                    render_kpi_card(name, data.get(name, pd.DataFrame()), color, RATE_SERIES[name])


def render_ticker(highlights):
    if not highlights:
        return
    content = "".join(f"<span>{h}</span>" for h in highlights)
    st.markdown(f'<div class="ticker-wrap"><div class="ticker">{content}{content}</div></div>',
                unsafe_allow_html=True)


def render_yield_curve_gauge(api_key: str, start: str, end: str):
    df = fetch_series("T10Y2Y", api_key, start, end, units="lin")
    if df.empty:
        st.info("Yield-curve data unavailable for this range.")
        return
    latest = float(df.iloc[-1]["value"])
    latest_date = df.iloc[-1]["date"]
    fig = go.Figure(go.Indicator(
        mode="gauge+number",
        value=latest,
        number={"suffix": " pts", "font": {"size": 34, "color": "#111111", "family": "Times New Roman, Times, serif"}},
        gauge={
            "axis": {"range": [-1.5, 2.5], "tickcolor": "#333333", "tickfont": {"color": "#333333"}},
            "bar": {"color": "#111111", "thickness": 0.25},
            "bgcolor": "white",
            "borderwidth": 1,
            "bordercolor": "#111111",
            "steps": [
                {"range": [-1.5, 0], "color": "#e3b8b8"},
                {"range": [0, 0.5], "color": "#e6d9a8"},
                {"range": [0.5, 2.5], "color": "#b9d9c4"},
            ],
            "threshold": {"line": {"color": "#8a1a1a", "width": 3}, "thickness": 0.85, "value": latest},
        },
    ))
    fig.update_layout(height=250, margin=dict(l=20, r=20, t=15, b=10),
                       paper_bgcolor="white", font={"color": "#111111", "family": "Times New Roman, Times, serif"})
    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
    status = "Inverted (recession-watch zone)" if latest < 0 else ("Flat" if latest < 0.5 else "Normal / healthy")
    st.caption(f"10Y-2Y spread: **{latest:.2f} pts** as of {latest_date:%b %d, %Y} — {status}")


def pick_trend_defaults(selected, preferred=("10-Year Treasury", "Effective Fed Funds Rate", "2-Year Treasury", "SOFR")):
    chosen = [p for p in preferred if p in selected]
    for s in selected:
        if len(chosen) >= 2:
            break
        if s not in chosen:
            chosen.append(s)
    return chosen[:2]


def render_trend_chart(data: dict, names: list, bands=None):
    plot_names = [n for n in names if not data.get(n, pd.DataFrame()).empty]
    if not plot_names:
        st.info("Select at least one series above to plot.")
        return
    fig = go.Figure()
    for i, name in enumerate(plot_names):
        df = data[name]
        fig.add_trace(go.Scatter(
            x=df["date"], y=df["value"], name=name, mode="lines",
            line=dict(color=CHART_PALETTE[i % len(CHART_PALETTE)], width=2.2),
        ))
    if bands:
        for b_start, b_end in bands:
            fig.add_vrect(x0=b_start, x1=b_end, fillcolor="#d9d9d9", opacity=0.55, layer="below", line_width=0)
    fig.update_layout(
        height=290, margin=dict(l=10, r=10, t=35, b=10),
        paper_bgcolor="white", plot_bgcolor="white",
        font={"color": "#111111", "family": "Times New Roman, Times, serif"},
        legend=dict(orientation="h", y=1.18, x=0),
        xaxis=dict(showgrid=False, linecolor="#111111"), hovermode="x unified",
        yaxis=dict(showgrid=True, gridcolor="#e5e5e5", title="Value", linecolor="#111111"),
    )
    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------
st.markdown(APP_CSS, unsafe_allow_html=True)
st.sidebar.title("Settings")

api_key = st.sidebar.text_input(
    "FRED API Key", value=get_default_api_key(), type="password",
    help="Free key: https://fred.stlouisfed.org/docs/api/api_key.html",
)

if not api_key:
    st.markdown(
        "<span class='brand-dots'><span class='dot-navy'></span><span class='dot-crimson'></span>"
        "<span class='dot-forest'></span><span class='dot-grey'></span></span>",
        unsafe_allow_html=True,
    )
    st.title("FRED Interest Rate Dashboard")
    st.info(
        "Enter your FRED API key in the sidebar to get started. Get a free one at "
        "[fred.stlouisfed.org/docs/api/api_key.html](https://fred.stlouisfed.org/docs/api/api_key.html)."
    )
    st.stop()

st.sidebar.subheader("Date Range")
preset = st.sidebar.selectbox("Quick range", PRESET_RANGES, index=4)

today = date.today()
preset_start_map = {
    "1M": today - timedelta(days=30), "3M": today - timedelta(days=91),
    "6M": today - timedelta(days=182), "YTD": date(today.year, 1, 1),
    "1Y": today - timedelta(days=365), "5Y": today - timedelta(days=365 * 5),
    "10Y": today - timedelta(days=365 * 10), "Max": date(1954, 1, 1),
}

if preset == "Custom":
    start_date = st.sidebar.date_input("Start date", value=today - timedelta(days=365), max_value=today)
    end_date = st.sidebar.date_input("End date", value=today, max_value=today)
    if start_date >= end_date:
        st.sidebar.error("Start date must be before end date.")
        st.stop()
else:
    start_date = preset_start_map[preset]
    end_date = today
    st.sidebar.caption(f"{start_date:%b %d, %Y} → {end_date:%b %d, %Y}")

st.sidebar.subheader("Rates to Track")
sorted_names = sorted(RATE_SERIES.keys(), key=lambda n: (CATEGORY_ORDER.index(RATE_SERIES[n]["cat"]), n))
selected_rates = st.sidebar.multiselect(
    "Choose rates (grouped by category)",
    options=sorted_names,
    default=DEFAULT_RATES,
    format_func=lambda n: f"{RATE_SERIES[n]['cat']} — {n}",
)

st.sidebar.subheader("Chart Options")
show_recessions = st.sidebar.checkbox("Shade NBER recessions on charts", value=True)

st.sidebar.subheader("Live")
if HAS_AUTOREFRESH:
    live_refresh = st.sidebar.checkbox("Auto-refresh every 5 min", value=False)
    if live_refresh:
        st_autorefresh(interval=5 * 60 * 1000, key="auto_refresh")
if st.sidebar.button("Refresh now"):
    st.cache_data.clear()
    st.rerun()

with st.sidebar.expander("About this dashboard"):
    st.write(
        "Data comes live from the FRED API (Federal Reserve Bank of St. Louis). "
        "Not affiliated with or endorsed by the Federal Reserve. YoY series (CPI, "
        "Core CPI, PCE, M2) use FRED's built-in 'percent change from a year ago' "
        "transform rather than a client-side calculation. Recession shading uses "
        "the NBER-based recession indicator (USREC). FRED doesn't publish a news "
        "feed, so **Data Highlights** are generated from the rate data itself, and "
        "**Upcoming Events** lists official scheduled release dates from FRED's "
        "Releases API."
    )

# ---------------------------------------------------------------------------
# Fetch data once, used across all tabs
# ---------------------------------------------------------------------------
all_needed = sorted(set(selected_rates) | set(HEADLINE_NAMES))
data = {}
if all_needed:
    try:
        data = load_selected_data(tuple(all_needed), start_date.isoformat(), end_date.isoformat(), api_key)
    except requests.exceptions.HTTPError as e:
        st.error(f"FRED API error — double-check your API key. Details: {e}")
        st.stop()
    except Exception as e:
        st.error(f"Unexpected error fetching data: {e}")
        st.stop()

recession_bands = []
if show_recessions:
    try:
        recession_bands = fetch_recession_bands(api_key, start_date.isoformat(), end_date.isoformat())
    except Exception:
        recession_bands = []

# ---------------------------------------------------------------------------
# Header
# ---------------------------------------------------------------------------
st.markdown(
    "<span class='brand-dots'><span class='dot-navy'></span><span class='dot-crimson'></span>"
    "<span class='dot-forest'></span><span class='dot-grey'></span></span>",
    unsafe_allow_html=True,
)
st.title("FRED Interest Rate Dashboard")
st.caption("Live data from the Federal Reserve Economic Data (FRED) API")

tab_dashboard, tab_historical, tab_export = st.tabs(
    ["Dashboard", "Historical Comparison & Analysis", "Export"]
)

# ---- Dashboard tab ---------------------------------------------------------
with tab_dashboard:
    st.markdown(
        f"<span class='live-dot'></span>"
        f"<span style='color:#333333;font-size:13px;'>Live &nbsp;/&nbsp; last updated {datetime.now():%I:%M:%S %p}</span>",
        unsafe_allow_html=True,
    )

    st.markdown(
        "<div class='cat-header' style='border-bottom-color:#111111;'>At A Glance — Core Macro Indicators</div>",
        unsafe_allow_html=True,
    )
    headline_cols = st.columns(len(HEADLINE_NAMES))
    for col, name in zip(headline_cols, HEADLINE_NAMES):
        with col:
            render_kpi_card(name, data.get(name, pd.DataFrame()), "#111111", RATE_SERIES[name], headline=True)

    if not selected_rates:
        st.info("Select rates from the sidebar to build out the dashboard below.")
    else:
        highlights = []
        for name in selected_rates:
            df = data.get(name, pd.DataFrame())
            if df.empty or len(df) < 2:
                continue
            meta = RATE_SERIES[name]
            latest_val, prior_delta, year_delta, latest_date = latest_and_delta(df)
            if latest_val is None:
                continue
            arrow = "▲" if prior_delta > 0 else ("▼" if prior_delta < 0 else "—")
            highlights.append(
                f"<strong>{name}</strong> {latest_val:.{meta['dp']}f}{meta['suffix']} "
                f"({arrow} {abs(prior_delta):.{meta['dp']}f}{meta['suffix']} vs. prior reading)"
            )
        render_ticker(highlights)
        with st.expander("View highlights as text"):
            for h in highlights:
                st.markdown(f"- {h}", unsafe_allow_html=True)

        grid_names = [n for n in selected_rates if n not in HEADLINE_NAMES]
        render_kpi_grid(grid_names, data)

        st.markdown("<div class='section-gap'></div>", unsafe_allow_html=True)
        st.markdown("<div class='row-bar' style='background:#111111;'></div>", unsafe_allow_html=True)
        gauge_col, trend_col = st.columns([1, 2.3])
        with gauge_col:
            st.subheader("Yield Curve Health")
            render_yield_curve_gauge(api_key, start_date.isoformat(), end_date.isoformat())
        with trend_col:
            st.subheader("Rate Trend")
            available = [n for n in selected_rates if not data.get(n, pd.DataFrame()).empty]
            default_trend = pick_trend_defaults(available)
            trend_names = st.multiselect(
                "Series to plot", options=available, default=default_trend,
                max_selections=4, key="trend_series",
            )
            render_trend_chart(data, trend_names, recession_bands if show_recessions else [])

        st.divider()
        st.subheader("Upcoming FRED Data Releases")
        st.caption("Scheduled release dates for rate & macro data, next 30 days (source: FRED Releases API).")
        try:
            rel_df = filter_relevant_releases(fetch_upcoming_releases(api_key, days_ahead=30))
        except Exception as e:
            rel_df = pd.DataFrame()
            st.caption(f"Could not load release calendar right now ({e}).")
        if rel_df.empty:
            st.write("No upcoming releases found in this window.")
        else:
            show_df = rel_df[["date", "release_name"]].rename(columns={"date": "Date", "release_name": "Release"})
            show_df["Date"] = show_df["Date"].dt.strftime("%a, %b %d, %Y")
            st.dataframe(show_df, hide_index=True, use_container_width=True)

# ---- Historical Comparison & Analysis tab ----------------------------------
with tab_historical:
    st.subheader("Historical Comparison")
    if not selected_rates:
        st.info("Select at least one rate from the sidebar to compare history.")
    else:
        opt_col1, opt_col2 = st.columns(2)
        with opt_col1:
            normalize = st.checkbox("Normalize (index = 100 at period start)", value=False)
        with opt_col2:
            show_bands_hist = st.checkbox("Shade NBER recessions", value=show_recessions, key="hist_bands")

        frames = []
        for name in selected_rates:
            df = data.get(name, pd.DataFrame())
            if df.empty:
                continue
            tmp = df.copy()
            tmp["Series"] = name
            if normalize:
                base = tmp["value"].iloc[0]
                if base:
                    tmp["value"] = (tmp["value"] / base) * 100
            frames.append(tmp)

        if frames:
            long_df = pd.concat(frames, ignore_index=True)
            fig = px.line(
                long_df, x="date", y="value", color="Series",
                color_discrete_sequence=CHART_PALETTE,
                labels={"value": "Index (start=100)" if normalize else "Percent / Value", "date": "Date"},
            )
            fig.update_layout(
                template="plotly_white", paper_bgcolor="white", plot_bgcolor="white",
                font={"family": "Times New Roman, Times, serif", "color": "#111111"},
                hovermode="x unified", legend_title_text="",
            )
            fig.update_xaxes(showgrid=False, linecolor="#111111")
            fig.update_yaxes(showgrid=True, gridcolor="#e5e5e5", linecolor="#111111")
            if show_bands_hist:
                for b_start, b_end in recession_bands:
                    fig.add_vrect(x0=b_start, x1=b_end, fillcolor="#d9d9d9", opacity=0.55, layer="below", line_width=0)
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.write("No data available for the selected rates/date range.")

        st.divider()
        st.subheader("Summary Statistics")
        stats_rows = []
        for name in selected_rates:
            df = data.get(name, pd.DataFrame())
            if df.empty:
                continue
            meta = RATE_SERIES[name]
            dp = meta["dp"]
            latest = df["value"].iloc[-1]
            mean = df["value"].mean()
            std = df["value"].std()
            window_365 = df[df["date"] >= (df["date"].iloc[-1] - pd.Timedelta(days=365))]
            stats_rows.append({
                "Rate": name, "Series ID": meta["id"],
                "Latest": round(latest, dp),
                "52W Min": round(window_365["value"].min(), dp) if not window_365.empty else None,
                "52W Max": round(window_365["value"].max(), dp) if not window_365.empty else None,
                "Period Min": round(df["value"].min(), dp),
                "Period Max": round(df["value"].max(), dp),
                "Period Avg": round(mean, dp),
                "Std Dev": round(std, dp) if pd.notna(std) else None,
                "Z-Score": round((latest - mean) / std, 2) if std else None,
                "Percentile (period)": round((df["value"] <= latest).mean() * 100, 1),
                "Change (period)": round(df["value"].iloc[-1] - df["value"].iloc[0], dp),
            })
        if stats_rows:
            st.dataframe(pd.DataFrame(stats_rows), hide_index=True, use_container_width=True)
            st.caption("Z-Score and Percentile are computed over the selected date range, not the full series history.")

        st.divider()
        st.subheader("Correlation Matrix")
        merged = None
        for name in selected_rates:
            df = data.get(name, pd.DataFrame())
            if df.empty:
                continue
            s = df.set_index("date")["value"].rename(name)
            merged = s.to_frame() if merged is None else merged.join(s, how="outer")
        if merged is not None and merged.shape[1] >= 2:
            merged = merged.sort_index().ffill().dropna()
            if len(merged) >= 5:
                corr = merged.corr()
                fig_corr = px.imshow(
                    corr, text_auto=".2f", color_continuous_scale="RdBu_r",
                    zmin=-1, zmax=1, aspect="auto",
                )
                fig_corr.update_layout(
                    template="plotly_white", paper_bgcolor="white",
                    font={"family": "Times New Roman, Times, serif", "color": "#111111"},
                    height=max(320, 55 * len(corr)),
                )
                st.plotly_chart(fig_corr, use_container_width=True)
                st.caption("Pairwise correlation of values across selected series, forward-filled to align mismatched release dates.")
            else:
                st.write("Not enough overlapping data points in this range to compute correlations.")
        else:
            st.write("Select at least two rates to see their correlation.")

        with st.expander("View raw data tables"):
            for name in selected_rates:
                df = data.get(name, pd.DataFrame())
                if df.empty:
                    continue
                st.write(f"**{name}** ({RATE_SERIES[name]['id']})")
                st.dataframe(df.rename(columns={"date": "Date", "value": "Value"}),
                             hide_index=True, use_container_width=True, height=200)

# ---- Export tab -------------------------------------------------------------
with tab_export:
    st.subheader("Export Data")
    if not selected_rates:
        st.info("Select at least one rate from the sidebar to export.")
    else:
        fmt = st.radio("Format", ["Wide (one column per rate)", "Long (tidy: one row per date/series)"],
                        horizontal=True)

        frames = []
        for name in selected_rates:
            df = data.get(name, pd.DataFrame())
            if df.empty:
                continue
            tmp = df.copy()
            tmp["Series"] = name
            tmp["Series ID"] = RATE_SERIES[name]["id"]
            frames.append(tmp)

        if not frames:
            st.write("No data to export.")
        else:
            long_df = pd.concat(frames, ignore_index=True).rename(columns={"date": "Date", "value": "Value"})

            if fmt.startswith("Wide"):
                export_df = long_df.pivot_table(index="Date", columns="Series", values="Value").reset_index()
            else:
                export_df = long_df[["Date", "Series", "Series ID", "Value"]].sort_values(["Date", "Series"])

            st.dataframe(export_df, use_container_width=True, hide_index=True)

            csv_bytes = export_df.to_csv(index=False).encode("utf-8")
            st.download_button("Download CSV", data=csv_bytes,
                                file_name=f"fred_rates_{start_date}_{end_date}.csv", mime="text/csv")

            try:
                buf = io.BytesIO()
                with pd.ExcelWriter(buf, engine="xlsxwriter") as writer:
                    export_df.to_excel(writer, index=False, sheet_name="FRED Rates")
                st.download_button(
                    "Download Excel", data=buf.getvalue(),
                    file_name=f"fred_rates_{start_date}_{end_date}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )
            except ImportError:
                st.caption("Install `xlsxwriter` to enable Excel export (CSV is available above).")
