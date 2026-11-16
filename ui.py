
import plotly.graph_objects as go
import plotly.io as pio
import plotly.express as px
import streamlit as st

PALETTES = {
    "light": {
        "bg": "#F5F6FA", "card": "#FFFFFF", "text": "#1B2133", "muted": "#667085",
        "border": "#E4E7EC", "primary": "#4F46E5", "primary_soft": "#EEF0FF",
        "accent": "#F59E0B", "shadow": "0 1px 2px rgba(16,24,40,.06), 0 4px 14px rgba(16,24,40,.05)",
        "grid": "#E8EAF0", "sidebar_a": "#FFFFFF", "sidebar_b": "#F1F2FA",
    },
    "dark": {
        "bg": "#0E1220", "card": "#171C2E", "text": "#E8EAF2", "muted": "#98A2B3",
        "border": "#2A3150", "primary": "#818CF8", "primary_soft": "#222849",
        "accent": "#FBBF24", "shadow": "0 1px 2px rgba(0,0,0,.35), 0 6px 18px rgba(0,0,0,.25)",
        "grid": "#262D49", "sidebar_a": "#121729", "sidebar_b": "#0E1220",
    },
}

# Chart colours chosen to stay readable on both light and dark backgrounds.
COLORWAY = ["#6366F1", "#F59E0B", "#10B981", "#EC4899", "#06B6D4", "#8B5CF6", "#EF4444", "#84CC16"]
LABEL_COLORS = {
    "Star": "#10B981",
    "Hidden Gem": "#8B5CF6",
    "Window-Shopper": "#F59E0B",
    "Low Priority": "#94A3B8",
    "Not Enough Data": "#64748B",
}


def theme_type() -> str:
    """'light' or 'dark', whatever the viewer picked in Streamlit's Settings menu."""
    try:
        return "dark" if st.context.theme.type == "dark" else "light"
    except Exception:
        return "light"


def set_plotly_theme():
    """Chart template that works on any background. Text and grid colours are set by CSS
    (see apply_theme), so charts follow Streamlit's Light/Dark switch instantly."""
    tpl = go.layout.Template(pio.templates["plotly_white"])
    tpl.layout.update(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="Inter, system-ui, sans-serif", color="#8A93A6", size=13),
        colorway=COLORWAY,
        xaxis=dict(gridcolor="rgba(128,128,128,0.22)", zerolinecolor="rgba(128,128,128,0.35)",
                   linecolor="rgba(128,128,128,0.35)", automargin=True),
        yaxis=dict(gridcolor="rgba(128,128,128,0.22)", zerolinecolor="rgba(128,128,128,0.35)",
                   linecolor="rgba(128,128,128,0.35)", automargin=True),
        legend=dict(bgcolor="rgba(0,0,0,0)"),
        hoverlabel=dict(bgcolor="#1B2133", font_color="#FFFFFF", bordercolor="#1B2133"),
        margin=dict(l=10, r=20, t=30, b=20),
    )
    pio.templates["holiday_shelf"] = tpl
    pio.templates.default = "holiday_shelf"
    px.defaults.template = "holiday_shelf"


def apply_theme() -> str:
    """Inject the stylesheet and chart theme. Call once, right after set_page_config."""
    # Streamlit marks .stApp with color-scheme: light|dark for the ACTIVE theme (including a
    # manual Light/Dark pick in Settings), so light-dark() always matches what is on screen.
    set_plotly_theme()
    ld = lambda k: f"light-dark({PALETTES['light'][k]}, {PALETTES['dark'][k]})"
    mode = theme_type()
    st.html(f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');
.stApp {{
  --hs-bg:{ld('bg')}; --hs-card:{ld('card')}; --hs-text:{ld('text')}; --hs-muted:{ld('muted')};
  --hs-border:{ld('border')}; --hs-primary:{ld('primary')}; --hs-soft:{ld('primary_soft')};
  --hs-accent:{ld('accent')}; --hs-grid:{ld('grid')};
  --hs-shadow: 0 1px 2px rgba(0,0,0,.08), 0 6px 18px rgba(0,0,0,.08);
}}
html, body, .stApp, .stMarkdown, p, label, button, input, textarea, [data-baseweb] {{ font-family: Inter, system-ui, -apple-system, 'Segoe UI', sans-serif; }}
[data-testid="stIconMaterial"], .material-symbols-rounded, [class*="material-symbols"] {{ font-family: 'Material Symbols Rounded' !important; }}
.block-container {{ padding-top: 2.2rem; padding-bottom: 4rem; max-width: 1240px; }}

/* ---- headings ---- */
h1 {{ font-weight: 800 !important; letter-spacing: -0.025em; }}
h1::after {{ content:""; display:block; width:56px; height:5px; border-radius:6px; margin-top:10px;
            background: linear-gradient(90deg, #6366F1, #EC4899, #F59E0B); }}
h2, h3 {{ font-weight: 700 !important; letter-spacing: -0.015em; }}
[data-testid="stCaptionContainer"] {{ color: var(--hs-muted); }}

/* ---- sidebar ---- */
[data-testid="stSidebar"] {{
  background: linear-gradient(180deg, {ld('sidebar_a')} 0%, {ld('sidebar_b')} 100%);
  border-right: 1px solid var(--hs-border);
}}
[data-testid="stSidebar"] h1 {{ display:none; }}
[data-testid="stSidebar"] [role="radiogroup"] {{ gap: 4px; }}
[data-testid="stSidebar"] [role="radiogroup"] label {{
  padding: 9px 12px; border-radius: 10px; width: 100%; cursor: pointer;
  border: 1px solid transparent; transition: background .15s, border-color .15s;
}}
[data-testid="stSidebar"] [role="radiogroup"] label > div:first-child {{ display: none; }}
[data-testid="stSidebar"] [role="radiogroup"] label:hover {{ background: var(--hs-soft); }}
[data-testid="stSidebar"] [role="radiogroup"] label:has(input:checked) {{
  background: var(--hs-soft); border-color: var(--hs-primary); font-weight: 700;
}}
[data-testid="stSidebar"] [role="radiogroup"] label:has(input:checked) p {{ color: var(--hs-primary); }}

/* ---- KPI cards (st.metric) ---- */
[data-testid="stMetric"] {{
  background: var(--hs-card); border: 1px solid var(--hs-border); border-radius: 16px;
  padding: 16px 20px; box-shadow: var(--hs-shadow);
}}
[data-testid="stMetricLabel"] p {{ color: var(--hs-muted); font-size: .78rem; font-weight: 600;
                                   text-transform: uppercase; letter-spacing: .06em; }}
[data-testid="stMetricValue"] {{ font-weight: 800; letter-spacing: -0.02em; }}

/* ---- bordered containers become cards ---- */
div[data-testid="stVerticalBlock"][class*="stVerticalBlock"] > div[data-testid="stVerticalBlockBorderWrapper"] {{
  background: var(--hs-card); border-radius: 16px; box-shadow: var(--hs-shadow);
}}

/* ---- buttons ---- */
.stButton > button, .stDownloadButton > button, .stLinkButton > a {{
  border-radius: 10px; border: 1px solid var(--hs-border); font-weight: 600;
  transition: transform .06s, border-color .15s, box-shadow .15s;
}}
.stButton > button:hover, .stDownloadButton > button:hover, .stLinkButton > a:hover {{
  border-color: var(--hs-primary); color: var(--hs-primary); box-shadow: 0 0 0 3px var(--hs-soft);
}}
.stButton > button:active {{ transform: scale(.98); }}

/* ---- tabs, tables, alerts, expanders ---- */
.stTabs [data-baseweb="tab-list"] {{ gap: 6px; }}
.stTabs [data-baseweb="tab"] {{ border-radius: 10px 10px 0 0; font-weight: 600; }}
[data-testid="stDataFrame"] {{ border: 1px solid var(--hs-border); border-radius: 14px; overflow: hidden; }}
[data-testid="stAlert"] {{ border-radius: 14px; }}
[data-testid="stExpander"] {{ border-radius: 14px; border: 1px solid var(--hs-border); background: var(--hs-card); }}
[data-testid="stPlotlyChart"] {{ background: var(--hs-card); border: 1px solid var(--hs-border);
                                 border-radius: 16px; padding: 10px; box-shadow: var(--hs-shadow); }}

[data-testid="stPlotlyChart"] div, .js-plotly-plot, .plot-container, .svg-container {{ background: transparent !important; }}

/* ---- chart text and grid follow the active theme ---- */
.js-plotly-plot .plotly text, .js-plotly-plot .legendtext, .js-plotly-plot .gtitle {{ fill: var(--hs-text) !important; }}
.js-plotly-plot .hoverlayer text {{ fill: #FFFFFF !important; }}
.js-plotly-plot .bartext {{ fill: #FFFFFF !important; }}
.js-plotly-plot .gridlayer path, .js-plotly-plot .zerolinelayer path {{ stroke: var(--hs-grid) !important; }}

/* ---- custom components (hero, insight cards, brand) ---- */
.hs-hero {{ background: linear-gradient(135deg, #4F46E5 0%, #7C3AED 55%, #EC4899 100%);
           color: #fff; border-radius: 22px; padding: 34px 38px; margin: 6px 0 22px;
           box-shadow: 0 12px 34px rgba(79,70,229,.30); position: relative; overflow: hidden; }}
.hs-hero::after {{ content:"🎁"; position:absolute; right:30px; top:14px; font-size:96px; opacity:.18; }}
.hs-hero h2 {{ color:#fff; margin:0 0 8px; font-size:1.9rem; font-weight:800 !important; }}
.hs-hero p {{ color: rgba(255,255,255,.92); margin:0; font-size:1.05rem; max-width:720px; line-height:1.55; }}
.hs-chips {{ margin-top:16px; display:flex; gap:8px; flex-wrap:wrap; }}
.hs-chip {{ background: rgba(255,255,255,.18); border:1px solid rgba(255,255,255,.28); color:#fff;
           padding:5px 12px; border-radius:999px; font-size:.8rem; font-weight:600; }}
.hs-card {{ background: var(--hs-card); border:1px solid var(--hs-border); border-radius:18px;
           padding:20px 22px; box-shadow: var(--hs-shadow); height:100%; }}
.hs-card .k {{ color: var(--hs-muted); font-size:.78rem; font-weight:700; text-transform:uppercase; letter-spacing:.06em; }}
.hs-card .v {{ font-size:2.1rem; font-weight:800; letter-spacing:-0.03em; margin:4px 0 6px; }}
.hs-card .d {{ color: var(--hs-muted); font-size:.92rem; line-height:1.5; }}
.hs-card.star  {{ border-top: 4px solid #10B981; }}
.hs-card.gem   {{ border-top: 4px solid #8B5CF6; }}
.hs-card.shop  {{ border-top: 4px solid #F59E0B; }}
.hs-row {{ display:flex; justify-content:space-between; align-items:center; gap:12px;
          padding:12px 0; border-bottom:1px solid var(--hs-border); }}
.hs-row:last-child {{ border-bottom:none; }}
.hs-row .n {{ font-weight:600; }}
.hs-row .s {{ color: var(--hs-muted); font-size:.85rem; }}
.hs-pill {{ background: var(--hs-soft); color: var(--hs-primary); font-weight:700; font-size:.82rem;
           padding:4px 10px; border-radius:999px; white-space:nowrap; }}
.hs-brand {{ display:flex; align-items:center; gap:12px; padding: 6px 4px 14px; }}
.hs-logo {{ width:42px; height:42px; border-radius:12px; display:flex; align-items:center; justify-content:center;
           font-size:22px; background: linear-gradient(135deg,#4F46E5,#EC4899); box-shadow:0 6px 16px rgba(79,70,229,.35); }}
.hs-brand .t {{ font-weight:800; font-size:1.15rem; letter-spacing:-0.02em; color: var(--hs-text); line-height:1.1; }}
.hs-brand .s {{ color: var(--hs-muted); font-size:.74rem; }}
.hs-basket {{ background: var(--hs-card); border:1px solid var(--hs-border); border-radius:14px; padding:12px 14px; box-shadow: var(--hs-shadow); }}
.hs-basket .t {{ font-weight:700; font-size:.9rem; }}
.hs-basket .s {{ color: var(--hs-muted); font-size:.76rem; margin-top:2px; }}
.hs-bar {{ height:7px; border-radius:6px; background: var(--hs-soft); margin-top:9px; overflow:hidden; }}
.hs-bar > span {{ display:block; height:100%; border-radius:6px; background: linear-gradient(90deg,#6366F1,#EC4899); }}
</style>
""")
    return mode


def sidebar_brand():
    st.sidebar.html(
        '<div class="hs-brand"><div class="hs-logo">🎁</div>'
        '<div><div class="t">Holiday Shelf</div>'
        '<div class="s">Merchandising planner</div></div></div>'
    )


def sidebar_basket(n: int, low: int = 10, high: int = 15):
    pct = min(n / high, 1.0) * 100
    if n == 0:
        msg = f"Target: {low}–{high} products"
    elif n < low:
        msg = f"Add {low - n} more to reach {low}"
    elif n <= high:
        msg = "In the recommended range"
    else:
        msg = f"{n - high} over the recommended {high}"
    st.sidebar.html(
        f'<div class="hs-basket"><div class="t">🛒 Shortlist: {n} product{"s" if n != 1 else ""}</div>'
        f'<div class="s">{msg}</div><div class="hs-bar"><span style="width:{pct:.0f}%"></span></div></div>'
    )


def hero(title: str, text: str, chips: list[str]):
    chips_html = "".join(f'<span class="hs-chip">{c}</span>' for c in chips)
    st.html(f'<div class="hs-hero"><h2>{title}</h2><p>{text}</p><div class="hs-chips">{chips_html}</div></div>')


def insight_card(kind: str, label: str, value: str, text: str):
    return (f'<div class="hs-card {kind}"><div class="k">{label}</div>'
            f'<div class="v">{value}</div><div class="d">{text}</div></div>')


def plot(fig, **kwargs):
    """st.plotly_chart that keeps our theme (Streamlit's own chart theme would override it)."""
    kwargs.setdefault("width", "stretch")
    return st.plotly_chart(fig, theme=None, **kwargs)