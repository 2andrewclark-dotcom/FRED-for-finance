"""
FRED Interest Rate Dashboard — dark, modern theme
----------------------------------------------------
Live interest-rate data from the FRED API, styled as a dark KPI dashboard
with row-colored accent bars, sparkline metric cards, a yield-curve gauge,
a scrolling headline ticker, and optional live auto-refresh.

Tabs:
  - Dashboard: KPI cards w/ sparklines, yield-curve gauge, rate trend chart,
               scrolling data-highlights ticker, upcoming FRED release dates.
  - Historical Comparison: overlay multiple rates, normalize, summary stats.
  - Export: download the selected rates/date-range as CSV or Excel.

Run with:  streamlit run app.py
Requires a free FRED API key: https://fred.stlouisfed.org/docs/api/api_key.html
Put the included .streamlit/config.toml next to app.py for the native
Streamlit widgets (sidebar, inputs, tables) to pick up the dark theme too.
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
st.set_page_config(page_title="FRED Rate Dashboard", page_icon="📊", layout="wide")

FRED_BASE = "https://api.stlouisfed.org/fred"

RATE_SERIES = {
    "Effective Federal Funds Rate": "FEDFUNDS",
    "Fed Funds Rate (Daily)": "DFF",
    "SOFR": "SOFR",
    "3-Month Treasury": "DGS3MO",
    "1-Year Treasury": "DGS1",
    "2-Year Treasury": "DGS2",
    "5-Year Treasury": "DGS5",
    "10-Year Treasury": "DGS10",
    "30-Year Treasury": "DGS30",
    "10Y-2Y Treasury Spread": "T10Y2Y",
    "30-Year Fixed Mortgage": "MORTGAGE30US",
    "15-Year Fixed Mortgage": "MORTGAGE15US",
    "Bank Prime Loan Rate": "DPRIME",
}

RATE_ICONS = {
    "Effective Federal Funds Rate": "🏦",
    "Fed Funds Rate (Daily)": "🏦",
    "SOFR": "💵",
    "3-Month Treasury": "📄",
    "1-Year Treasury": "📄",
    "2-Year Treasury": "📈",
    "5-Year Treasury": "📈",
    "10-Year Treasury": "📈",
    "30-Year Treasury": "📈",
    "10Y-2Y Treasury Spread": "📉",
    "30-Year Fixed Mortgage": "🏠",
    "15-Year Fixed Mortgage": "🏠",
    "Bank Prime Loan Rate": "🏢",
}

DEFAULT_RATES = [
    "Effective Federal Funds Rate",
    "10-Year Treasury",
    "2-Year Treasury",
    "30-Year Fixed Mortgage",
    "SOFR",
]

RELEASE_KEYWORDS = [
    "interest rate", "h.15", "selected interest",
    "consumer price index", "producer price index",
    "employment situation", "employment cost",
    "gross domestic product", "personal income",
    "beige book", "flow of funds", "money stock", "h.6",
    "federal open market", "fomc",
]

PRESET_RANGES = ["1M", "3M", "6M", "YTD", "1Y", "5Y", "10Y", "Max", "Custom"]

# Row-level accent colors, cycled per row of KPI cards (mirrors reference design)
ROW_COLORS = ["#f5a623", "#4a90e2", "#2dd4bf"]
CHART_PALETTE = ["#2dd4bf", "#4a90e2", "#f5a623", "#f87171", "#a78bfa",
                  "#34d399", "#fbbf24", "#60a5fa", "#f472b6", "#38bdf8",
                  "#facc15", "#c084fc", "#4ade80"]

DARK_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');

html, body, [class*="css"] { font-family: 'Inter', sans-serif; }
#MainMenu {visibility: hidden;}
footer {visibility: hidden;}

.brand-dots span { display:inline-block; width:9px; height:9px; border-radius:50%; margin-right:5px; }
.dot-orange{background:#f5a623;} .dot-blue{background:#4a90e2;} .dot-teal{background:#2dd4bf;} .dot-grey{background:#4b5163;}

.live-dot { display:inline-block; width:8px; height:8px; border-radius:50%; background:#34d399;
  margin-right:6px; animation: pulse 2s infinite; }
@keyframes pulse {
  0% { box-shadow: 0 0 0 0 rgba(52,211,153,0.55); }
  70% { box-shadow: 0 0 0 8px rgba(52,211,153,0); }
  100% { box-shadow: 0 0 0 0 rgba(52,211,153,0); }
}

.ticker-wrap { width:100%; overflow:hidden; background:#1c2030; border:1px solid rgba(255,255,255,0.07);
  border-radius:10px; padding:10px 0; margin: 6px 0 18px 0; }
.ticker { display:inline-block; white-space:nowrap; padding-left:100%; animation: ticker 38s linear infinite; }
.ticker:hover { animation-play-state: paused; }
.ticker span { display:inline-block; padding:0 2.2rem; color:#c7ccdb; font-size:14px; }
.ticker span strong { color:#e8eaf0; }
@keyframes ticker { 0% { transform:translate(0,0);} 100% { transform:translate(-50%,0);} }

.row-bar { height:3px; border-radius:2px; margin:2px 0 12px 0; opacity:0.9; }

.kpi-card { background:#1c2030; border:1px solid rgba(255,255,255,0.07); border-radius:12px;
  padding:16px 18px 12px 18px; margin-bottom:6px; min-height:190px; }
.kpi-label { color:#8b92a8; font-size:13px; font-weight:600; margin-bottom:8px; }
.kpi-value { font-size:28px; font-weight:800; margin-bottom:12px; line-height:1; }
.kpi-compare { display:flex; justify-content:space-between; gap:10px; margin-bottom:8px; }
.kpi-compare-item { flex:1; }
.kpi-compare-label { color:#5b6274; font-size:11px; margin-bottom:2px; }
.kpi-up { color:#34d399; font-weight:700; font-size:13px; }
.kpi-down { color:#f87171; font-weight:700; font-size:13px; }
.kpi-flat { color:#8b92a8; font-weight:700; font-size:13px; }
.kpi-spark { margin-top:4px; line-height:0; }
.kpi-meta { color:#5b6274; font-size:11px; margin-top:8px; }

.section-gap { margin-top: 6px; }
</style>
"""

# ---------------------------------------------------------------------------
# Data access (cached)
# ---------------------------------------------------------------------------
@st.cache_data(ttl=3600, show_spinner=False)
def fetch_series(series_id: str, api_key: str, start: str, end: str) -> pd.DataFrame:
    url = f"{FRED_BASE}/series/observations"
    params = {
        "series_id": series_id, "api_key": api_key, "file_type": "json",
        "observation_start": start, "observation_end": end,
    }
    r = requests.get(url, params=params, timeout=20)
    r.raise_for_status()
    obs = r.json().get("observations", [])
    df = pd.DataFrame(obs)
    if df.empty:
        return pd.DataFrame(columns=["date", "value"])
    df["date"] = pd.to_datetime(df["date"])
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    return df[["date", "value"]].dropna().sort_values("date").reset_index(drop=True)


@st.cache_data(ttl=3600, show_spinner="Fetching data from FRED...")
def load_selected_data(names: tuple, start: str, end: str, api_key: str) -> dict:
    return {name: fetch_series(RATE_SERIES[name], api_key, start, end) for name in names}


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


def latest_and_delta(df: pd.DataFrame, lookback_days: int = 30):
    if df.empty:
        return None, None, None
    latest_row = df.iloc[-1]
    latest_val, latest_date = latest_row["value"], latest_row["date"]
    cutoff = latest_date - pd.Timedelta(days=lookback_days)
    prior = df[df["date"] <= cutoff]
    prior_val = prior.iloc[-1]["value"] if not prior.empty else df.iloc[0]["value"]
    return latest_val, latest_val - prior_val, latest_date


def get_default_api_key() -> str:
    try:
        return st.secrets["FRED_API_KEY"]
    except Exception:
        return os.environ.get("FRED_API_KEY", "")


# ---------------------------------------------------------------------------
# Dynamic-component helpers
# ---------------------------------------------------------------------------
def sparkline_svg(values, color="#2dd4bf", width=180, height=40) -> str:
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
        f'fill="{color}" fill-opacity="0.15" stroke="none"/>'
    )
    return (
        f'<svg width="100%" height="{height}" viewBox="0 0 {width} {height}" '
        f'preserveAspectRatio="none" xmlns="http://www.w3.org/2000/svg">'
        f'{fill_path}'
        f'<path d="{path}" fill="none" stroke="{color}" stroke-width="2.2" '
        f'stroke-linecap="round" stroke-linejoin="round"/></svg>'
    )


def fmt_delta(d):
    if d is None:
        return "–", "kpi-flat"
    if d > 0:
        return f"▲ {abs(d):.2f}", "kpi-up"
    if d < 0:
        return f"▼ {abs(d):.2f}", "kpi-down"
    return "• 0.00", "kpi-flat"


def render_kpi_card(name: str, df: pd.DataFrame, accent: str):
    icon = RATE_ICONS.get(name, "📊")
    if df.empty:
        st.markdown(
            f"<div class='kpi-card'><div class='kpi-label'>{icon} {name}</div>"
            f"<div class='kpi-value' style='color:{accent};'>N/A</div></div>",
            unsafe_allow_html=True,
        )
        return
    latest_val, period_delta, latest_date = latest_and_delta(df, lookback_days=30)
    _, year_delta, _ = latest_and_delta(df, lookback_days=365)
    p_text, p_cls = fmt_delta(period_delta)
    y_text, y_cls = fmt_delta(year_delta)
    spark = sparkline_svg(df["value"].tail(60).tolist(), color=accent)

    html = f"""
    <div class="kpi-card">
      <div class="kpi-label">{icon} {name}</div>
      <div class="kpi-value" style="color:{accent};">{latest_val:.2f}%</div>
      <div class="kpi-compare">
        <div class="kpi-compare-item">
          <div class="kpi-compare-label">PREVIOUS PERIOD (30D)</div>
          <div class="{p_cls}">{p_text}</div>
        </div>
        <div class="kpi-compare-item">
          <div class="kpi-compare-label">PREVIOUS YEAR</div>
          <div class="{y_cls}">{y_text}</div>
        </div>
      </div>
      <div class="kpi-spark">{spark}</div>
      <div class="kpi-meta">as of {latest_date:%b %d, %Y} · {RATE_SERIES[name]}</div>
    </div>
    """
    st.markdown(html, unsafe_allow_html=True)


def render_kpi_grid(names, data):
    if not names:
        return
    n_cols = min(4, len(names))
    rows = [names[i:i + n_cols] for i in range(0, len(names), n_cols)]
    for row_idx, row_names in enumerate(rows):
        accent = ROW_COLORS[row_idx % len(ROW_COLORS)]
        st.markdown(f"<div class='row-bar' style='background:{accent};'></div>", unsafe_allow_html=True)
        cols = st.columns(len(row_names))
        for col, name in zip(cols, row_names):
            with col:
                render_kpi_card(name, data.get(name, pd.DataFrame()), accent)


def render_ticker(highlights):
    if not highlights:
        return
    content = "".join(f"<span>{h}</span>" for h in highlights)
    st.markdown(f'<div class="ticker-wrap"><div class="ticker">{content}{content}</div></div>',
                unsafe_allow_html=True)


def render_yield_curve_gauge(api_key: str, start: str, end: str):
    df = fetch_series("T10Y2Y", api_key, start, end)
    if df.empty:
        st.info("Yield-curve data unavailable for this range.")
        return
    latest = float(df.iloc[-1]["value"])
    latest_date = df.iloc[-1]["date"]
    fig = go.Figure(go.Indicator(
        mode="gauge+number",
        value=latest,
        number={"suffix": " pts", "font": {"size": 34, "color": "#e8eaf0"}},
        gauge={
            "axis": {"range": [-1.5, 2.5], "tickcolor": "#8b92a8", "tickfont": {"color": "#8b92a8"}},
            "bar": {"color": "#e8eaf0", "thickness": 0.25},
            "bgcolor": "rgba(0,0,0,0)",
            "borderwidth": 0,
            "steps": [
                {"range": [-1.5, 0], "color": "#f87171"},
                {"range": [0, 0.5], "color": "#f5a623"},
                {"range": [0.5, 2.5], "color": "#34d399"},
            ],
            "threshold": {"line": {"color": "white", "width": 3}, "thickness": 0.85, "value": latest},
        },
    ))
    fig.update_layout(height=250, margin=dict(l=20, r=20, t=15, b=10),
                       paper_bgcolor="rgba(0,0,0,0)", font={"color": "#e8eaf0"})
    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
    status = "Inverted — recession-watch zone" if latest < 0 else ("Flat" if latest < 0.5 else "Normal / healthy")
    st.caption(f"10Y-2Y spread: **{latest:.2f} pts** as of {latest_date:%b %d, %Y} — {status}")


def render_trend_chart(data: dict, names: list):
    plot_names = [n for n in names if not data.get(n, pd.DataFrame()).empty][:2]
    if not plot_names:
        st.info("Select rates in the sidebar to see the trend chart.")
        return
    fig = go.Figure()
    palette = ["#2dd4bf", "#93c5fd"]
    for i, name in enumerate(plot_names):
        df = data[name]
        fig.add_trace(go.Scatter(
            x=df["date"], y=df["value"], name=name, mode="lines",
            line=dict(color=palette[i % 2], width=2.5),
            fill="tozeroy" if i == 0 else None,
            fillcolor="rgba(45,212,191,0.12)" if i == 0 else None,
        ))
    fig.update_layout(
        height=290, margin=dict(l=10, r=10, t=35, b=10),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font={"color": "#e8eaf0"}, legend=dict(orientation="h", y=1.15, x=0),
        xaxis=dict(showgrid=False), hovermode="x unified",
        yaxis=dict(showgrid=True, gridcolor="rgba(255,255,255,0.07)", title="%"),
    )
    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------
st.markdown(DARK_CSS, unsafe_allow_html=True)
st.sidebar.title("⚙️ Settings")

api_key = st.sidebar.text_input(
    "FRED API Key", value=get_default_api_key(), type="password",
    help="Free key: https://fred.stlouisfed.org/docs/api/api_key.html",
)

if not api_key:
    st.markdown(
        "<span class='brand-dots'><span class='dot-orange'></span><span class='dot-blue'></span>"
        "<span class='dot-teal'></span><span class='dot-grey'></span></span>",
        unsafe_allow_html=True,
    )
    st.title("📊 FRED Interest Rate Dashboard")
    st.info(
        "👋 Enter your FRED API key in the sidebar to get started. Get a free one at "
        "[fred.stlouisfed.org/docs/api/api_key.html](https://fred.stlouisfed.org/docs/api/api_key.html)."
    )
    st.stop()

st.sidebar.subheader("📅 Date Range")
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

st.sidebar.subheader("💹 Rates to Track")
selected_rates = st.sidebar.multiselect("Choose rates", options=list(RATE_SERIES.keys()), default=DEFAULT_RATES)

st.sidebar.subheader("⚡ Live")
if HAS_AUTOREFRESH:
    live_refresh = st.sidebar.checkbox("Auto-refresh every 5 min", value=False)
    if live_refresh:
        st_autorefresh(interval=5 * 60 * 1000, key="auto_refresh")
if st.sidebar.button("🔄 Refresh now"):
    st.cache_data.clear()
    st.rerun()

with st.sidebar.expander("ℹ️ About this dashboard"):
    st.write(
        "Data comes live from the FRED API (Federal Reserve Bank of St. Louis). "
        "Not affiliated with or endorsed by the Federal Reserve. FRED doesn't publish "
        "a news feed, so **Data Highlights** are generated from the rate data itself, "
        "and **Upcoming Events** lists official scheduled release dates from FRED's "
        "Releases API."
    )

# ---------------------------------------------------------------------------
# Fetch data once, used across all tabs
# ---------------------------------------------------------------------------
data = {}
if selected_rates:
    try:
        data = load_selected_data(tuple(selected_rates), start_date.isoformat(), end_date.isoformat(), api_key)
    except requests.exceptions.HTTPError as e:
        st.error(f"FRED API error — double-check your API key. Details: {e}")
        st.stop()
    except Exception as e:
        st.error(f"Unexpected error fetching data: {e}")
        st.stop()

# ---------------------------------------------------------------------------
# Header
# ---------------------------------------------------------------------------
st.markdown(
    "<span class='brand-dots'><span class='dot-orange'></span><span class='dot-blue'></span>"
    "<span class='dot-teal'></span><span class='dot-grey'></span></span>",
    unsafe_allow_html=True,
)
st.title("📊 FRED Interest Rate Dashboard")
st.caption("Live data from the Federal Reserve Economic Data (FRED) API")

tab_dashboard, tab_historical, tab_export = st.tabs(["🏠 Dashboard", "📈 Historical Comparison", "⬇️ Export"])

# ---- Dashboard tab ---------------------------------------------------------
with tab_dashboard:
    if not selected_rates:
        st.info("Select at least one rate from the sidebar to see the dashboard.")
    else:
        st.markdown(
            f"<span class='live-dot'></span>"
            f"<span style='color:#8b92a8;font-size:13px;'>Live · last updated {datetime.now():%I:%M:%S %p}</span>",
            unsafe_allow_html=True,
        )

        highlights = []
        for name in selected_rates:
            df = data.get(name, pd.DataFrame())
            latest_val, delta, latest_date = latest_and_delta(df)
            if latest_val is None:
                continue
            direction = "up" if delta > 0 else ("down" if delta < 0 else "flat")
            highlights.append(
                f"<strong>{name}</strong> {latest_val:.2f}% "
                f"({direction} {abs(delta):.2f} pts / 30d)"
            )
        render_ticker(highlights)
        with st.expander("View highlights as text"):
            for h in highlights:
                st.markdown(f"- {h}", unsafe_allow_html=True)

        render_kpi_grid(selected_rates, data)

        st.markdown("<div class='section-gap'></div>", unsafe_allow_html=True)
        st.markdown(f"<div class='row-bar' style='background:{ROW_COLORS[2]};'></div>", unsafe_allow_html=True)
        gauge_col, trend_col = st.columns([1, 2.3])
        with gauge_col:
            st.subheader("Yield Curve Health")
            render_yield_curve_gauge(api_key, start_date.isoformat(), end_date.isoformat())
        with trend_col:
            st.subheader("Rate Trend")
            render_trend_chart(data, selected_rates)

        st.divider()
        st.subheader("🗓️ Upcoming FRED Data Releases")
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

# ---- Historical Comparison tab --------------------------------------------
with tab_historical:
    st.subheader("📈 Historical Comparison")
    if not selected_rates:
        st.info("Select at least one rate from the sidebar to compare history.")
    else:
        normalize = st.checkbox("Normalize (index = 100 at period start)", value=False)

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
                labels={"value": "Index (start=100)" if normalize else "Percent (%)", "date": "Date"},
            )
            fig.update_layout(
                template="plotly_dark", paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                hovermode="x unified", legend_title_text="",
            )
            fig.update_xaxes(showgrid=False)
            fig.update_yaxes(showgrid=True, gridcolor="rgba(255,255,255,0.08)")
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
            stats_rows.append({
                "Rate": name, "Series ID": RATE_SERIES[name],
                "Latest": round(df["value"].iloc[-1], 2),
                "Min": round(df["value"].min(), 2), "Max": round(df["value"].max(), 2),
                "Average": round(df["value"].mean(), 2),
                "Change (period)": round(df["value"].iloc[-1] - df["value"].iloc[0], 2),
            })
        if stats_rows:
            st.dataframe(pd.DataFrame(stats_rows), hide_index=True, use_container_width=True)

        with st.expander("View raw data tables"):
            for name in selected_rates:
                df = data.get(name, pd.DataFrame())
                if df.empty:
                    continue
                st.write(f"**{name}** ({RATE_SERIES[name]})")
                st.dataframe(df.rename(columns={"date": "Date", "value": "Value"}),
                             hide_index=True, use_container_width=True, height=200)

# ---- Export tab -------------------------------------------------------------
with tab_export:
    st.subheader("⬇️ Export Data")
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
            tmp["Series ID"] = RATE_SERIES[name]
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
