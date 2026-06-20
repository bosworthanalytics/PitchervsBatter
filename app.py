"""
MLB Player Comparison Dashboard
Jung Hoo Lee (SF Giants) vs Ceddanne Rafaela (BOS Red Sox)
"""

import os
import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import plotly.express as px
from plotly.subplots import make_subplots

# ── Page config ────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Lee vs. Rafaela | MLB Analytics",
    page_icon="baseball",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Colors & constants ─────────────────────────────────────────────────────────
C = {
    "Jung Hoo Lee":     "#FD5A1E",
    "Ceddanne Rafaela": "#BD3039",
}
BG       = "#0E1117"
CARD_BG  = "#1A1D2E"
LINE_CLR = "#2D3250"
TEXT     = "#FAFAFA"
SUBTEXT  = "#9BA3B8"
GOLD     = "#C4A962"

MONTH_ORDER = ["March","April","May","June","July","August","September","October"]

def hex_to_rgba(hex_color, alpha=0.15):
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"rgba({r},{g},{b},{alpha})"

def grade_label(g):
    if g >= 80: return "Elite"
    if g >= 70: return "Well Above Avg"
    if g >= 65: return "Plus-Plus"
    if g >= 60: return "Plus"
    if g >= 55: return "Above Avg"
    if g == 50: return "Average"
    if g >= 45: return "Fringe"
    if g >= 40: return "Below Avg"
    return "Well Below Avg"

SCOUTING = {
    "Jung Hoo Lee":     {"Hit": 55, "Power": 40, "Speed": 50, "Field": 55, "Arm": 55},
    "Ceddanne Rafaela": {"Hit": 40, "Power": 45, "Speed": 70, "Field": 70, "Arm": 70},
}

HS = {
    "Jung Hoo Lee":
        "https://img.mlbstatic.com/mlb-photos/image/upload/d_people:generic:headshot:67:current.png"
        "/w_213,q_auto:best/v1/people/808982/headshot/67/current",
    "Ceddanne Rafaela":
        "https://img.mlbstatic.com/mlb-photos/image/upload/d_people:generic:headshot:67:current.png"
        "/w_213,q_auto:best/v1/people/678882/headshot/67/current",
}

TEAMS = {
    "Jung Hoo Lee":     "San Francisco Giants",
    "Ceddanne Rafaela": "Boston Red Sox",
}

# ── CSS ────────────────────────────────────────────────────────────────────────
st.markdown("""
<style>
/* Main background */
.stApp { background-color: #0E1117; }
[data-testid="stSidebar"] { background-color: #1A1D2E; border-right: 1px solid #2D3250; }

/* Cards */
.metric-card {
    background: #1A1D2E;
    border: 1px solid #2D3250;
    border-radius: 10px;
    padding: 16px 20px;
    text-align: center;
    margin: 4px 0;
}
.metric-value { font-size: 2rem; font-weight: 700; margin: 4px 0; }
.metric-label { font-size: 0.75rem; color: #9BA3B8; text-transform: uppercase; letter-spacing: 1px; }
.metric-delta { font-size: 0.85rem; margin-top: 4px; }

/* Player header card */
.player-card {
    background: #1A1D2E;
    border-radius: 12px;
    padding: 20px;
    text-align: center;
    border-top: 4px solid;
    margin-bottom: 12px;
}
.player-name { font-size: 1.4rem; font-weight: 700; color: #FAFAFA; margin: 8px 0 2px 0; }
.player-team { font-size: 0.9rem; color: #9BA3B8; }

/* Section headers */
.section-header {
    font-size: 1.1rem;
    font-weight: 600;
    color: #C4A962;
    text-transform: uppercase;
    letter-spacing: 1.5px;
    border-bottom: 1px solid #2D3250;
    padding-bottom: 6px;
    margin: 16px 0 12px 0;
}

/* Page title */
.page-title {
    font-size: 2.2rem;
    font-weight: 800;
    color: #FAFAFA;
    text-align: center;
    margin-bottom: 4px;
}
.page-subtitle {
    font-size: 1rem;
    color: #9BA3B8;
    text-align: center;
    margin-bottom: 24px;
}

/* Tab styling */
.stTabs [data-baseweb="tab"] {
    font-size: 0.9rem;
    font-weight: 600;
    color: #9BA3B8;
}
.stTabs [aria-selected="true"] { color: #C4A962 !important; }

/* Divider */
.divider { border-top: 1px solid #2D3250; margin: 20px 0; }

/* Hide streamlit defaults */
#MainMenu, footer, header { visibility: hidden; }
</style>
""", unsafe_allow_html=True)

# ── Data loading ───────────────────────────────────────────────────────────────
DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output")

@st.cache_data
def load_data():
    batting    = pd.read_csv(os.path.join(DATA_DIR, "batting_standard.csv"))
    statcast   = pd.read_csv(os.path.join(DATA_DIR, "statcast_advanced.csv"))
    discipline = pd.read_csv(os.path.join(DATA_DIR, "plate_discipline.csv"))
    defense    = pd.read_csv(os.path.join(DATA_DIR, "defense.csv"))
    # Enforce month order for line charts
    for df in [batting, statcast, discipline]:
        df["Month"] = pd.Categorical(df["Month"], categories=MONTH_ORDER + ["Season Total"], ordered=True)
    return batting, statcast, discipline, defense

batting, statcast, discipline, defense = load_data()
ALL_SEASONS = sorted(batting["Season"].unique().tolist())

# ── Sidebar ────────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("## Filters")
    sel_seasons = st.multiselect("Season(s)", ALL_SEASONS, default=ALL_SEASONS, key="seasons")
    st.markdown("---")
    st.markdown("### Players")
    show_lee  = st.checkbox("Jung Hoo Lee",    value=True)
    show_raf  = st.checkbox("Ceddanne Rafaela", value=True)
    st.markdown("---")
    st.markdown("### About")
    st.markdown(
        "Data from **Baseball Savant**, **FanGraphs**, and **MLB Stats API** "
        "via `pybaseball`. "
        "Covers MLB careers from debut through June 2026."
    )
    st.markdown(
        "*Built with Python · Streamlit · Plotly*"
    )

active_players = []
if show_lee:  active_players.append("Jung Hoo Lee")
if show_raf:  active_players.append("Ceddanne Rafaela")

if not active_players:
    st.warning("Select at least one player in the sidebar.")
    st.stop()

# ── Filter helpers ─────────────────────────────────────────────────────────────
def filt(df, period=None):
    d = df[df["Player"].isin(active_players) & df["Season"].isin(sel_seasons)]
    if period and "Period" in d.columns:
        d = d[d["Period"] == period]
    return d

def season_total(df):
    return filt(df, period="Season")

def monthly(df):
    return filt(df, period="Monthly")

# ── Chart theme ────────────────────────────────────────────────────────────────
LAYOUT = dict(
    paper_bgcolor=CARD_BG, plot_bgcolor=CARD_BG,
    font=dict(color=TEXT, family="Segoe UI, sans-serif"),
    legend=dict(bgcolor=CARD_BG, bordercolor=LINE_CLR, borderwidth=1,
                font=dict(size=12)),
    margin=dict(l=16, r=16, t=40, b=16),
    xaxis=dict(gridcolor=LINE_CLR, zerolinecolor=LINE_CLR),
    yaxis=dict(gridcolor=LINE_CLR, zerolinecolor=LINE_CLR),
)

def apply_layout(fig, **kw):
    fig.update_layout(**{**LAYOUT, **kw})
    return fig

# ── Page header ────────────────────────────────────────────────────────────────
st.markdown('<div class="page-title">Jung Hoo Lee vs. Ceddanne Rafaela</div>', unsafe_allow_html=True)
st.markdown('<div class="page-subtitle">MLB Outfielder Comparison · 2023–2026 · Built with Statcast & FanGraphs Data</div>', unsafe_allow_html=True)

# Player header cards
hcols = st.columns([1, 0.15, 1])
for i, player in enumerate(["Jung Hoo Lee", "Ceddanne Rafaela"]):
    col = hcols[0] if player == "Jung Hoo Lee" else hcols[2]
    color = C[player]
    dim = "opacity:0.4;" if player not in active_players else ""
    with col:
        st.markdown(f"""
        <div class="player-card" style="border-top-color:{color};{dim}">
            <img src="{HS[player]}" width="100" style="border-radius:50%;border:3px solid {color};"
                 onerror="this.style.display='none'"/>
            <div class="player-name">{player}</div>
            <div class="player-team">{TEAMS[player]}</div>
        </div>
        """, unsafe_allow_html=True)

# ── Tabs ───────────────────────────────────────────────────────────────────────
t1, t2, t3, t4, t5 = st.tabs([
    "Overview", "Hitting", "Statcast", "Plate Discipline", "Defense"
])

# ════════════════════════════════════════════════════════════════════════════════
# TAB 1 — OVERVIEW
# ════════════════════════════════════════════════════════════════════════════════
with t1:
    st_totals  = season_total(batting)
    sc_totals  = season_total(statcast)
    disc_totals = season_total(discipline)

    # ── Stat Comparison: horizontal grouped bar, latest season, indexed to MLB avg ──
    st.markdown('<div class="section-header">Key Stats vs. MLB Average — Latest Season</div>', unsafe_allow_html=True)

    def latest_val(df, col):
        out = {}
        for p in active_players:
            sub = df[df["Player"] == p].sort_values("Season", ascending=False)
            v = sub[col].iloc[0] if len(sub) and pd.notna(sub[col].iloc[0]) else None
            out[p] = v
        return out

    # (label, dataframe, column, mlb_avg, display_fmt)
    COMP_METRICS = [
        ("AVG",          st_totals,    "AVG",         0.248, "{:.3f}"),
        ("OBP",          st_totals,    "OBP",         0.320, "{:.3f}"),
        ("SLG",          st_totals,    "SLG",         0.410, "{:.3f}"),
        ("OPS",          st_totals,    "OPS",         0.720, "{:.3f}"),
        ("xBA",          sc_totals,    "xBA",         0.248, "{:.3f}"),
        ("Avg EV (mph)", sc_totals,    "EV_avg",      88.5,  "{:.1f}"),
        ("Hard Hit %",   sc_totals,    "HardHit_pct", 37.5,  "{:.1f}%"),
        ("BB %",         disc_totals,  "BB_pct",       8.5,  "{:.1f}%"),
        ("K % (lower=better)", disc_totals, "K_pct", 23.0,  "{:.1f}%"),
    ]

    fig_comp = go.Figure()
    metric_labels = [m[0] for m in COMP_METRICS]
    for player in active_players:
        index_vals, text_vals = [], []
        for label, df, col, mlb_avg, fmt in COMP_METRICS:
            v = latest_val(df, col).get(player)
            if v is not None and mlb_avg:
                idx = (mlb_avg / v * 100) if "lower=better" in label else (v / mlb_avg * 100)
                index_vals.append(round(idx, 1))
                text_vals.append(fmt.format(v))
            else:
                index_vals.append(None)
                text_vals.append("N/A")
        fig_comp.add_trace(go.Bar(
            y=metric_labels, x=index_vals, name=player,
            orientation="h", marker_color=C[player],
            text=text_vals, textposition="outside",
            textfont=dict(color=TEXT, size=11),
            hovertemplate="<b>%{y}</b><br>" + player + ": %{text}<br>Index: %{x:.0f}<extra></extra>",
        ))
    fig_comp.add_vline(x=100, line_color=GOLD, line_dash="dash", line_width=2)
    fig_comp.add_annotation(x=100, y=len(metric_labels) - 0.5, text="MLB Avg (100)",
                            showarrow=False, font=dict(color=GOLD, size=11), xanchor="left", xshift=4)
    apply_layout(fig_comp, barmode="group", height=440,
                 title="Latest Season Performance Index — 100 = MLB Average",
                 xaxis=dict(range=[50, 170], gridcolor=LINE_CLR, title="Index (100 = MLB Avg)"),
                 legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1))
    st.plotly_chart(fig_comp, use_container_width=True)

    st.markdown('<div class="divider"></div>', unsafe_allow_html=True)

    # ── OPS by Season — legend on top ──────────────────────────────────────────
    st.markdown('<div class="section-header">OPS by Season</div>', unsafe_allow_html=True)
    ops_data = st_totals.sort_values("Season")
    fig_ops = go.Figure()
    for player in active_players:
        sub = ops_data[ops_data["Player"] == player]
        fig_ops.add_trace(go.Bar(
            x=sub["Season"].astype(str), y=sub["OPS"],
            name=player, marker_color=C[player], text=sub["OPS"].round(3),
            textposition="outside", textfont=dict(size=12, color=TEXT),
        ))
    fig_ops.add_hline(y=0.720, line_dash="dash", line_color=GOLD,
                      annotation_text="MLB Avg (.720)", annotation_font_color=GOLD,
                      annotation_position="top right")
    apply_layout(fig_ops, barmode="group", height=360,
                 yaxis=dict(range=[0, 1.1], gridcolor=LINE_CLR),
                 yaxis_title="OPS",
                 legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1))
    st.plotly_chart(fig_ops, use_container_width=True)

    st.markdown('<div class="divider"></div>', unsafe_allow_html=True)

    # ── Scouting Tool Grades (20-80 scale, FanGraphs) ──────────────────────────
    st.markdown('<div class="section-header">Scouting Tool Grades — 20-80 Scale (FanGraphs)</div>', unsafe_allow_html=True)

    tools = ["Hit", "Power", "Speed", "Field", "Arm"]
    fig_grades = go.Figure()
    for player in active_players:
        if player not in SCOUTING: continue
        grades = [SCOUTING[player].get(t, 50) for t in tools]
        labels = [f"{g} — {grade_label(g)}" for g in grades]
        fig_grades.add_trace(go.Bar(
            y=tools, x=grades, name=player, orientation="h",
            marker_color=C[player],
            text=labels, textposition="outside",
            textfont=dict(color=TEXT, size=11),
            hovertemplate="<b>%{y}</b><br>" + player + ": %{x}/80<extra></extra>",
        ))
    # Background grade zones
    fig_grades.add_vrect(x0=20, x1=40, fillcolor="rgba(231,76,60,0.08)",  line_width=0, layer="below")
    fig_grades.add_vrect(x0=40, x1=50, fillcolor="rgba(230,126,34,0.08)", line_width=0, layer="below")
    fig_grades.add_vrect(x0=50, x1=60, fillcolor="rgba(196,169,98,0.08)", line_width=0, layer="below")
    fig_grades.add_vrect(x0=60, x1=80, fillcolor="rgba(46,204,113,0.08)", line_width=0, layer="below")
    fig_grades.add_vline(x=50, line_color=GOLD, line_dash="dash", line_width=1.5)
    fig_grades.add_annotation(x=50, y=len(tools) - 0.5, text="Average (50)",
                              showarrow=False, font=dict(color=GOLD, size=11), xanchor="left", xshift=4)
    apply_layout(fig_grades, barmode="group", height=340,
                 title="Tool Grades on 20-80 Scale — Source: FanGraphs Scouting Reports",
                 xaxis=dict(range=[20, 100], gridcolor=LINE_CLR,
                            tickvals=[20,30,40,50,60,70,80],
                            title="Grade (20=Poor · 50=Average · 80=Elite)"),
                 legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1))
    st.plotly_chart(fig_grades, use_container_width=True)
    st.markdown("""
    <div style="padding:10px 14px;background:#1A1D2E;border-radius:8px;border-left:3px solid #C4A962;
                font-size:0.8rem;color:#9BA3B8;margin-top:-8px;">
    <b style="color:#C4A962;">20-80 Scale:</b>
    &nbsp;20 = Poor &nbsp;·&nbsp; 30 = Well Below Avg &nbsp;·&nbsp; 40 = Below Avg &nbsp;·&nbsp;
    45 = Fringe &nbsp;·&nbsp; 50 = Average &nbsp;·&nbsp; 55 = Above Avg &nbsp;·&nbsp;
    60 = Plus &nbsp;·&nbsp; 65 = Plus-Plus &nbsp;·&nbsp; 70 = Well Above Avg &nbsp;·&nbsp; 80 = Elite
    </div>
    """, unsafe_allow_html=True)

# ════════════════════════════════════════════════════════════════════════════════
# TAB 2 — HITTING
# ════════════════════════════════════════════════════════════════════════════════
with t2:
    st.markdown('<div class="section-header">Monthly Batting Trends</div>', unsafe_allow_html=True)
    mon = monthly(batting).sort_values(["Season","Month_Num"])

    sel_season_hit = st.selectbox("Season", ALL_SEASONS,
                                   index=len(ALL_SEASONS)-1, key="hit_season")
    mon_s = mon[mon["Season"] == sel_season_hit]

    c1, c2 = st.columns(2)
    for col_widget, metric, title, ref, ref_label in [
        (c1, "AVG", "Batting Average by Month", 0.248, "MLB Avg (.248)"),
        (c2, "OPS", "OPS by Month",             0.720, "MLB Avg (.720)"),
    ]:
        fig = go.Figure()
        for player in active_players:
            sub = mon_s[mon_s["Player"] == player].sort_values("Month_Num")
            fig.add_trace(go.Scatter(
                x=sub["Month"], y=sub[metric], mode="lines+markers",
                name=player, line=dict(color=C[player], width=2.5),
                marker=dict(size=7), hovertemplate=f"%{{x}}: %{{y:.3f}}<extra>{player}</extra>",
            ))
        fig.add_hline(y=ref, line_dash="dot", line_color=GOLD,
                      annotation_text=ref_label, annotation_font_color=GOLD)
        apply_layout(fig, title=title, height=320)
        col_widget.plotly_chart(fig, use_container_width=True)

    st.markdown('<div class="divider"></div>', unsafe_allow_html=True)
    st.markdown('<div class="section-header">Season-by-Season Totals</div>', unsafe_allow_html=True)

    c3, c4 = st.columns(2)
    tot = season_total(batting).sort_values("Season")
    for col_widget, metric, title, ref, ref_lab in [
        (c3, "OBP", "On-Base % by Season", 0.320, "MLB Avg (.320)"),
        (c4, "SLG", "Slugging % by Season", 0.410, "MLB Avg (.410)"),
    ]:
        fig = go.Figure()
        for player in active_players:
            sub = tot[tot["Player"] == player]
            fig.add_trace(go.Bar(
                x=sub["Season"].astype(str), y=sub[metric],
                name=player, marker_color=C[player],
                text=sub[metric].round(3), textposition="outside",
                textfont=dict(color=TEXT, size=11),
            ))
        fig.add_hline(y=ref, line_dash="dash", line_color=GOLD,
                      annotation_text=ref_lab, annotation_font_color=GOLD)
        apply_layout(fig, barmode="group", title=title, height=320,
                     yaxis=dict(range=[0, tot[metric].max()*1.2], gridcolor=LINE_CLR))
        col_widget.plotly_chart(fig, use_container_width=True)

    st.markdown('<div class="divider"></div>', unsafe_allow_html=True)
    st.markdown('<div class="section-header">Monthly HR & RBI</div>', unsafe_allow_html=True)

    c5, c6 = st.columns(2)
    for col_widget, metric, title in [(c5,"HR","Home Runs by Month"), (c6,"RBI","RBI by Month")]:
        fig = go.Figure()
        for player in active_players:
            sub = mon_s[mon_s["Player"] == player].sort_values("Month_Num")
            fig.add_trace(go.Bar(
                x=sub["Month"], y=sub[metric], name=player,
                marker_color=C[player],
                text=sub[metric], textposition="outside",
                textfont=dict(color=TEXT, size=11),
            ))
        apply_layout(fig, barmode="group", title=title, height=300)
        col_widget.plotly_chart(fig, use_container_width=True)

    st.markdown('<div class="divider"></div>', unsafe_allow_html=True)
    st.markdown('<div class="section-header">Full Season Totals Table</div>', unsafe_allow_html=True)
    display_cols = ["Player","Season","G","PA","AB","H","AVG","OBP","SLG","OPS","HR","RBI","SB","BB","SO"]
    tbl = season_total(batting)[display_cols].sort_values(["Player","Season"])
    st.dataframe(
        tbl.style.format({c: "{:.3f}" for c in ["AVG","OBP","SLG","OPS"]})
               .background_gradient(subset=["AVG","OBP","SLG","OPS"], cmap="RdYlGn")
               .set_properties(**{"background-color": CARD_BG, "color": TEXT}),
        use_container_width=True, hide_index=True,
    )

# ════════════════════════════════════════════════════════════════════════════════
# TAB 3 — STATCAST
# ════════════════════════════════════════════════════════════════════════════════
with t3:
    st.markdown('<div class="section-header">Expected Stats vs. Actual</div>', unsafe_allow_html=True)

    c1, c2 = st.columns(2)
    with c1:
        # xBA vs AVG scatter (monthly)
        merged = monthly(batting).merge(
            monthly(statcast)[["Player","Season","Month","xBA","xSLG","xwOBA"]],
            on=["Player","Season","Month"], how="inner"
        ).dropna(subset=["AVG","xBA"])

        fig_scat = go.Figure()
        mn_v = min(merged["AVG"].min(), merged["xBA"].min()) - 0.02
        mx_v = max(merged["AVG"].max(), merged["xBA"].max()) + 0.02
        fig_scat.add_trace(go.Scatter(
            x=[mn_v, mx_v], y=[mn_v, mx_v],
            mode="lines", line=dict(color=GOLD, dash="dot", width=1.5),
            name="AVG = xBA (neutral)", showlegend=True,
        ))
        for player in active_players:
            sub = merged[merged["Player"] == player]
            fig_scat.add_trace(go.Scatter(
                x=sub["AVG"], y=sub["xBA"], mode="markers",
                name=player, marker=dict(color=C[player], size=9, opacity=0.85),
                hovertemplate=(
                    f"<b>{player}</b><br>"
                    "AVG: %{x:.3f}<br>xBA: %{y:.3f}"
                    "<br>Season: %{customdata[0]}, %{customdata[1]}"
                    "<extra></extra>"
                ),
                customdata=sub[["Season","Month"]].values,
            ))
        apply_layout(fig_scat,
                     title="xBA vs. Actual AVG (Monthly) — Above line = getting unlucky",
                     xaxis_title="Actual AVG", yaxis_title="xBA",
                     height=380)
        st.plotly_chart(fig_scat, use_container_width=True)

    with c2:
        # xSLG vs SLG
        merged2 = monthly(batting).merge(
            monthly(statcast)[["Player","Season","Month","xSLG"]],
            on=["Player","Season","Month"], how="inner"
        ).dropna(subset=["SLG","xSLG"])

        fig_scat2 = go.Figure()
        mn2 = min(merged2["SLG"].min(), merged2["xSLG"].min()) - 0.02
        mx2 = max(merged2["SLG"].max(), merged2["xSLG"].max()) + 0.02
        fig_scat2.add_trace(go.Scatter(
            x=[mn2,mx2], y=[mn2,mx2], mode="lines",
            line=dict(color=GOLD, dash="dot", width=1.5), name="SLG = xSLG", showlegend=True,
        ))
        for player in active_players:
            sub = merged2[merged2["Player"] == player]
            fig_scat2.add_trace(go.Scatter(
                x=sub["SLG"], y=sub["xSLG"], mode="markers",
                name=player, marker=dict(color=C[player], size=9, opacity=0.85),
                hovertemplate=(
                    f"<b>{player}</b><br>SLG: %{{x:.3f}}<br>xSLG: %{{y:.3f}}"
                    "<br>%{customdata[0]}, %{customdata[1]}<extra></extra>"
                ),
                customdata=sub[["Season","Month"]].values,
            ))
        apply_layout(fig_scat2,
                     title="xSLG vs. Actual SLG — Above line = power underperforming",
                     xaxis_title="Actual SLG", yaxis_title="xSLG", height=380)
        st.plotly_chart(fig_scat2, use_container_width=True)

    st.markdown('<div class="divider"></div>', unsafe_allow_html=True)
    st.markdown('<div class="section-header">Exit Velocity & Barrel Rate</div>', unsafe_allow_html=True)

    c3, c4 = st.columns(2)
    sc_tot = season_total(statcast).sort_values("Season")
    for col_w, metric, title, ref, ref_lab in [
        (c3, "EV_avg", "Avg Exit Velocity by Season (mph)", 88.5, "MLB Avg 88.5 mph"),
        (c4, "HardHit_pct", "Hard Hit Rate by Season (%)", 37.5, "MLB Avg 37.5%"),
    ]:
        fig = go.Figure()
        for player in active_players:
            sub = sc_tot[sc_tot["Player"] == player].dropna(subset=[metric])
            fig.add_trace(go.Bar(
                x=sub["Season"].astype(str), y=sub[metric], name=player,
                marker_color=C[player],
                text=sub[metric].round(1), textposition="outside",
                textfont=dict(color=TEXT, size=11),
            ))
        fig.add_hline(y=ref, line_dash="dash", line_color=GOLD,
                      annotation_text=ref_lab, annotation_font_color=GOLD)
        apply_layout(fig, barmode="group", title=title, height=320)
        col_w.plotly_chart(fig, use_container_width=True)

    st.markdown('<div class="divider"></div>', unsafe_allow_html=True)
    st.markdown('<div class="section-header">Monthly Exit Velocity Trends</div>', unsafe_allow_html=True)

    sel_season_sc = st.selectbox("Season", ALL_SEASONS, index=len(ALL_SEASONS)-1, key="sc_season")
    mon_sc = monthly(statcast)
    mon_sc = mon_sc[mon_sc["Season"] == sel_season_sc].sort_values("Month_Num")

    c5, c6 = st.columns(2)
    for col_w, metric, title, ref, ref_lab in [
        (c5, "EV_avg",      "Avg Exit Velo by Month (mph)", 88.5, "MLB Avg 88.5"),
        (c6, "HardHit_pct", "Hard Hit % by Month",          37.5, "MLB Avg 37.5%"),
    ]:
        fig = go.Figure()
        for player in active_players:
            sub = mon_sc[mon_sc["Player"] == player].dropna(subset=[metric])
            fig.add_trace(go.Scatter(
                x=sub["Month"], y=sub[metric], mode="lines+markers",
                name=player, line=dict(color=C[player], width=2.5), marker=dict(size=7),
            ))
        fig.add_hline(y=ref, line_dash="dot", line_color=GOLD,
                      annotation_text=ref_lab, annotation_font_color=GOLD)
        apply_layout(fig, title=title, height=320)
        col_w.plotly_chart(fig, use_container_width=True)

    st.markdown('<div class="divider"></div>', unsafe_allow_html=True)
    st.markdown('<div class="section-header">Statcast Season Totals Table</div>', unsafe_allow_html=True)
    sc_disp = sc_tot[["Player","Season","xBA","xSLG","xwOBA","EV_avg","EV_max","LA_avg","Barrel_pct","HardHit_pct"]]
    st.dataframe(
        sc_disp.style.format({c: "{:.3f}" for c in ["xBA","xSLG","xwOBA"]}
                             | {c: "{:.1f}" for c in ["EV_avg","EV_max","LA_avg","Barrel_pct","HardHit_pct"]})
               .background_gradient(subset=["xBA","xSLG","EV_avg","HardHit_pct"], cmap="RdYlGn"),
        use_container_width=True, hide_index=True,
    )

# ════════════════════════════════════════════════════════════════════════════════
# TAB 4 — PLATE DISCIPLINE
# ════════════════════════════════════════════════════════════════════════════════
with t4:
    sel_season_pd = st.selectbox("Season", ALL_SEASONS, index=len(ALL_SEASONS)-1, key="pd_season")
    mon_pd = monthly(discipline)
    mon_pd = mon_pd[mon_pd["Season"] == sel_season_pd].sort_values("Month_Num")
    disc_tot = season_total(discipline)

    st.markdown('<div class="section-header">Monthly Discipline Trends</div>', unsafe_allow_html=True)
    c1, c2 = st.columns(2)
    for col_w, metric, title, ref, ref_lab, inv in [
        (c1, "Chase_pct", "Chase Rate by Month (%) — Lower is Better", 30.0, "MLB Avg 30%", False),
        (c2, "K_pct",     "Strikeout Rate by Month (%) — Lower is Better", 23.0, "MLB Avg 23%", False),
    ]:
        fig = go.Figure()
        for player in active_players:
            sub = mon_pd[mon_pd["Player"] == player].dropna(subset=[metric])
            fig.add_trace(go.Scatter(
                x=sub["Month"], y=sub[metric], mode="lines+markers",
                name=player, line=dict(color=C[player], width=2.5), marker=dict(size=7),
                hovertemplate="%{x}: %{y:.1f}%<extra>" + player + "</extra>",
            ))
        fig.add_hline(y=ref, line_dash="dot", line_color=GOLD,
                      annotation_text=ref_lab, annotation_font_color=GOLD)
        apply_layout(fig, title=title, height=320)
        col_w.plotly_chart(fig, use_container_width=True)

    c3, c4 = st.columns(2)
    for col_w, metric, title, ref, ref_lab in [
        (c3, "BB_pct",      "Walk Rate by Month (%) — Higher is Better", 8.5, "MLB Avg 8.5%"),
        (c4, "ZContact_pct","Zone Contact % by Month — Higher is Better", 84.0, "MLB Avg 84%"),
    ]:
        fig = go.Figure()
        for player in active_players:
            sub = mon_pd[mon_pd["Player"] == player].dropna(subset=[metric])
            fig.add_trace(go.Scatter(
                x=sub["Month"], y=sub[metric], mode="lines+markers",
                name=player, line=dict(color=C[player], width=2.5), marker=dict(size=7),
            ))
        fig.add_hline(y=ref, line_dash="dot", line_color=GOLD,
                      annotation_text=ref_lab, annotation_font_color=GOLD)
        apply_layout(fig, title=title, height=320)
        col_w.plotly_chart(fig, use_container_width=True)

    st.markdown('<div class="divider"></div>', unsafe_allow_html=True)
    st.markdown('<div class="section-header">Discipline Radar — Season Totals</div>', unsafe_allow_html=True)

    disc_metrics = {
        "Walk %":        ("BB_pct",       False),
        "K% (inv)":      ("K_pct",        True),
        "Chase (inv)":   ("Chase_pct",    True),
        "Zone Cont%":    ("ZContact_pct", False),
        "OOZ Contact":   ("OContact_pct", False),
        "Zone%":         ("Zone_pct",     False),
        "SwStr (inv)":   ("SwStr_pct",    True),
    }
    rc1, rc2 = st.columns([1, 1])
    with rc1:
        fig_dr = go.Figure()
        cats_d = list(disc_metrics.keys())
        for player in active_players:
            sub = disc_tot[disc_tot["Player"] == player]
            all_v_d = [sub[col].mean() for _, (col, _) in disc_metrics.items()]
            all_raw = {i: [disc_tot[col].mean() for _, (col, _) in disc_metrics.items()][i]
                       for i in range(len(cats_d))}
            scores_d = []
            for i, (lbl, (col, inv)) in enumerate(disc_metrics.items()):
                col_vals = disc_tot[col].dropna()
                mn, mx = col_vals.min(), col_vals.max()
                v = sub[col].mean() if len(sub) and pd.notna(sub[col].mean()) else mn
                rng = mx - mn
                n = (v - mn) / rng * 100 if rng > 0 else 50
                scores_d.append(100 - n if inv else n)
            scores_d.append(scores_d[0])
            fig_dr.add_trace(go.Scatterpolar(
                r=scores_d, theta=cats_d + [cats_d[0]],
                fill="toself", name=player,
                line=dict(color=C[player], width=2),
            ))
        fig_dr.update_layout(
            polar=dict(bgcolor=CARD_BG,
                       radialaxis=dict(visible=True, range=[0,100], gridcolor=LINE_CLR,
                                       tickfont=dict(color=SUBTEXT, size=9)),
                       angularaxis=dict(gridcolor=LINE_CLR, tickfont=dict(color=TEXT, size=10))),
            paper_bgcolor=CARD_BG, font=dict(color=TEXT),
            legend=dict(bgcolor=CARD_BG, bordercolor=LINE_CLR),
            margin=dict(l=50, r=50, t=30, b=30), height=370,
        )
        st.plotly_chart(fig_dr, use_container_width=True)

    with rc2:
        st.markdown('<div class="section-header">SwStr % by Season</div>', unsafe_allow_html=True)
        fig_sw = go.Figure()
        for player in active_players:
            sub = disc_tot[disc_tot["Player"] == player].dropna(subset=["SwStr_pct"])
            fig_sw.add_trace(go.Bar(
                x=sub["Season"].astype(str), y=sub["SwStr_pct"], name=player,
                marker_color=C[player], text=sub["SwStr_pct"].round(1),
                textposition="outside", textfont=dict(color=TEXT),
            ))
        fig_sw.add_hline(y=10.8, line_dash="dash", line_color=GOLD,
                         annotation_text="MLB Avg 10.8%", annotation_font_color=GOLD)
        apply_layout(fig_sw, barmode="group",
                     title="Swinging Strike Rate (lower = better bat control)", height=370)
        st.plotly_chart(fig_sw, use_container_width=True)

    st.markdown('<div class="divider"></div>', unsafe_allow_html=True)
    st.markdown('<div class="section-header">Plate Discipline Season Totals Table</div>', unsafe_allow_html=True)
    disc_disp_cols = ["Player","Season","K_pct","BB_pct","SwStr_pct","Chase_pct","ZContact_pct","OContact_pct","Contact_pct","Zone_pct"]
    disc_disp = disc_tot[[c for c in disc_disp_cols if c in disc_tot.columns]]
    fmt = {c: "{:.1f}" for c in disc_disp.select_dtypes("number").columns}
    st.dataframe(
        disc_disp.style.format(fmt)
                       .background_gradient(subset=["BB_pct","ZContact_pct","Contact_pct"], cmap="RdYlGn")
                       .background_gradient(subset=["K_pct","Chase_pct","SwStr_pct"], cmap="RdYlGn_r"),
        use_container_width=True, hide_index=True,
    )

# ════════════════════════════════════════════════════════════════════════════════
# TAB 5 — DEFENSE
# ════════════════════════════════════════════════════════════════════════════════
with t5:
    def_filt = defense[defense["Player"].isin(active_players)].sort_values("Season")

    st.markdown('<div class="section-header">Outs Above Average (OAA) — Career</div>', unsafe_allow_html=True)
    c1, c2 = st.columns(2)

    with c1:
        fig_oaa = go.Figure()
        for player in active_players:
            sub = def_filt[def_filt["Player"] == player].dropna(subset=["OAA"])
            fig_oaa.add_trace(go.Bar(
                x=sub["Season"].astype(str), y=sub["OAA"], name=player,
                marker_color=C[player],
                text=sub["OAA"].apply(lambda v: f"+{int(v)}" if v > 0 else str(int(v))),
                textposition="outside", textfont=dict(color=TEXT, size=12),
            ))
        fig_oaa.add_hline(y=0, line_color=GOLD, line_width=1.5)
        apply_layout(fig_oaa, barmode="group",
                     title="Outs Above Average by Season<br><sup>+OAA = better than average outfielder</sup>",
                     height=360, yaxis_title="OAA")
        st.plotly_chart(fig_oaa, use_container_width=True)

    with c2:
        fig_fr = go.Figure()
        for player in active_players:
            sub = def_filt[def_filt["Player"] == player].dropna(subset=["Fielding_Runs"])
            fig_fr.add_trace(go.Bar(
                x=sub["Season"].astype(str), y=sub["Fielding_Runs"], name=player,
                marker_color=C[player],
                text=sub["Fielding_Runs"].apply(lambda v: f"+{int(v)}" if v > 0 else str(int(v))),
                textposition="outside", textfont=dict(color=TEXT, size=12),
            ))
        fig_fr.add_hline(y=0, line_color=GOLD, line_width=1.5)
        apply_layout(fig_fr, barmode="group",
                     title="Fielding Runs Prevented by Season<br><sup>Statcast estimated run value of defensive plays</sup>",
                     height=360, yaxis_title="Fielding Runs")
        st.plotly_chart(fig_fr, use_container_width=True)

    st.markdown('<div class="divider"></div>', unsafe_allow_html=True)
    st.markdown('<div class="section-header">UZR & DRS Comparison</div>', unsafe_allow_html=True)

    c3, c4 = st.columns(2)
    for col_w, metric, title, ref_lab in [
        (c3, "UZR",     "Ultimate Zone Rating (UZR) by Season", "0 = avg"),
        (c4, "DRS",     "Defensive Runs Saved (DRS) by Season", "0 = avg"),
    ]:
        fig = go.Figure()
        for player in active_players:
            sub = def_filt[def_filt["Player"] == player].dropna(subset=[metric])
            fig.add_trace(go.Bar(
                x=sub["Season"].astype(str), y=sub[metric], name=player,
                marker_color=C[player],
                text=sub[metric].round(1), textposition="outside",
                textfont=dict(color=TEXT, size=11),
            ))
        fig.add_hline(y=0, line_color=GOLD, line_width=1.5,
                      annotation_text=ref_lab, annotation_font_color=GOLD)
        apply_layout(fig, barmode="group", title=title, height=320, yaxis_title=metric)
        col_w.plotly_chart(fig, use_container_width=True)

    st.markdown('<div class="divider"></div>', unsafe_allow_html=True)
    st.markdown('<div class="section-header">Directional OAA — Where Each Player Excels</div>', unsafe_allow_html=True)

    dir_cols = ["OAA_Infront", "OAA_Behind"]
    dir_labels = {"OAA_Infront": "In Front of Player", "OAA_Behind": "Behind Player"}
    if all(c in def_filt.columns for c in dir_cols):
        fig_dir = go.Figure()
        for player in active_players:
            sub = def_filt[def_filt["Player"] == player].dropna(subset=dir_cols)
            if sub.empty: continue
            latest_row = sub.sort_values("Season").iloc[-1]
            fig_dir.add_trace(go.Bar(
                name=player,
                x=[dir_labels[c] for c in dir_cols],
                y=[latest_row[c] for c in dir_cols],
                marker_color=C[player],
                text=[latest_row[c] for c in dir_cols],
                textposition="outside", textfont=dict(color=TEXT),
            ))
        fig_dir.add_hline(y=0, line_color=GOLD, line_width=1.5)
        apply_layout(fig_dir, barmode="group",
                     title="Directional OAA (Latest Season) — Balls In Front vs. Over Head",
                     height=320, yaxis_title="OAA")
        st.plotly_chart(fig_dir, use_container_width=True)

    st.markdown('<div class="divider"></div>', unsafe_allow_html=True)
    st.markdown('<div class="section-header">Full Defensive Stats Table</div>', unsafe_allow_html=True)
    def_disp = def_filt[["Player","Season","OAA","Fielding_Runs","UZR","UZR_150","DRS","Arm_runs","Range_runs","Error_runs"]]
    st.dataframe(
        def_disp.style.format({c: "{:.1f}" for c in def_disp.select_dtypes("number").columns}, na_rep="N/A")
                      .background_gradient(subset=["OAA","UZR","DRS"], cmap="RdYlGn"),
        use_container_width=True, hide_index=True,
    )

    st.markdown("""
    <div style="margin-top:16px;padding:14px;background:#1A1D2E;border-radius:8px;
                border-left:3px solid #C4A962;font-size:0.85rem;color:#9BA3B8;">
    <b style="color:#C4A962;">Metric Guide</b><br>
    <b>OAA</b> — Outs Above Average (Baseball Savant): Statcast probability model of how many extra outs a fielder makes vs. expectation.<br>
    <b>UZR</b> — Ultimate Zone Rating (FanGraphs): Zone-based runs saved vs. an average fielder at the same position.<br>
    <b>DRS</b> — Defensive Runs Saved (The Fielding Bible / FanGraphs): Composite metric combining range, arm, and error runs.<br>
    <b>Fielding Runs</b> — Statcast estimated run value of all defensive plays made.
    </div>
    """, unsafe_allow_html=True)

# ── Footer ─────────────────────────────────────────────────────────────────────
st.markdown('<div class="divider"></div>', unsafe_allow_html=True)
st.markdown("""
<div style="text-align:center;color:#9BA3B8;font-size:0.8rem;padding:8px 0 16px 0;">
Data: Baseball Savant (Statcast) &nbsp;·&nbsp; FanGraphs &nbsp;·&nbsp; MLB Stats API &nbsp;·&nbsp; pybaseball 2.2.7
&nbsp;&nbsp;|&nbsp;&nbsp; Built by Sean Bosworth &nbsp;·&nbsp; June 2026
</div>
""", unsafe_allow_html=True)
