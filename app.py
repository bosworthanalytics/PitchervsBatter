"""
MLB Player Comparison Dashboard
Compare any hitter vs. hitter  |  pitcher vs. pitcher
"""
import warnings, os, requests
warnings.filterwarnings("ignore")

import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go

PB_IMPORT_ERROR = None
try:
    from pybaseball import (batting_stats, pitching_stats,
                            statcast_batter, statcast_pitcher,
                            playerid_reverse_lookup)
    import pybaseball
    pybaseball.cache.enable()
    HAS_PB = True
except Exception as _e:
    HAS_PB = False
    PB_IMPORT_ERROR = str(_e)

# ── Page ───────────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="MLB Player Comparison | Analytics",
    page_icon="baseball",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Constants ──────────────────────────────────────────────────────────────────
ALL_SEASONS   = [2023, 2024, 2025, 2026]
PA_COL        = "#FD5A1E"   # Player A — orange
PB_COL        = "#3B82F6"   # Player B — blue
GOLD          = "#C4A962"
CARD_BG       = "#1A1D2E"
LINE_CLR      = "#2D3250"
TEXT          = "#FAFAFA"
SUBTEXT       = "#9BA3B8"

SEASON_DATES = {
    2023: ("2023-03-30", "2023-10-01"),
    2024: ("2024-03-20", "2024-09-29"),
    2025: ("2025-03-27", "2025-09-28"),
    2026: ("2026-03-27", "2026-06-30"),
}
MONTH_NAMES = {3:"March",4:"April",5:"May",6:"June",
               7:"July",8:"August",9:"September",10:"October"}

HIT_AVG = {
    "AVG":0.248,"OBP":0.320,"SLG":0.410,"OPS":0.720,
    "wOBA":0.317,"wRC+":100.0,"K%":23.0,"BB%":8.5,
    "SwStr%":10.8,"O-Swing%":30.0,"Z-Contact%":84.0,
    "EV_avg":88.5,"HardHit%":37.5,
}
PIT_AVG = {
    "ERA":4.20,"WHIP":1.28,
    "K%":23.0,"BB%":8.5,"K-BB%":14.5,"K/9":9.0,"BB/9":3.1,
}

SCOUTING = {
    "Jung Hoo Lee":     {"Hit":55,"Power":40,"Speed":50,"Field":55,"Arm":55},
    "Ceddanne Rafaela": {"Hit":40,"Power":45,"Speed":70,"Field":70,"Arm":70},
}

PITCH_NAMES = {
    "FF":"4-Seam FB","SI":"Sinker","FC":"Cutter","SL":"Slider",
    "CU":"Curveball","KC":"Knuckle-Curve","CH":"Changeup","FS":"Splitter",
    "ST":"Sweeper","SV":"Slurve","KN":"Knuckleball","EP":"Eephus","FO":"Forkball",
}

def grade_label(g):
    if g>=80: return "Elite"
    if g>=70: return "Well Above Avg"
    if g>=65: return "Plus-Plus"
    if g>=60: return "Plus"
    if g>=55: return "Above Avg"
    if g>=50: return "Average"
    if g>=45: return "Fringe"
    if g>=40: return "Below Avg"
    return "Well Below Avg"

LAYOUT = dict(
    paper_bgcolor=CARD_BG, plot_bgcolor=CARD_BG,
    font=dict(color=TEXT, family="Segoe UI, sans-serif"),
    legend=dict(bgcolor=CARD_BG, bordercolor=LINE_CLR, borderwidth=1, font=dict(size=12)),
    margin=dict(l=16, r=16, t=50, b=16),
    xaxis=dict(gridcolor=LINE_CLR, zerolinecolor=LINE_CLR),
    yaxis=dict(gridcolor=LINE_CLR, zerolinecolor=LINE_CLR),
)
def apply_layout(fig, **kw):
    fig.update_layout(**{**LAYOUT, **kw}); return fig

# ── CSS ────────────────────────────────────────────────────────────────────────
st.markdown("""<style>
.stApp{background-color:#0E1117}
[data-testid="stSidebar"]{background-color:#1A1D2E;border-right:1px solid #2D3250}
.player-card{background:#1A1D2E;border-radius:12px;padding:18px;text-align:center;
             border-top:4px solid;margin-bottom:12px}
.player-name{font-size:1.3rem;font-weight:700;color:#FAFAFA;margin:8px 0 2px}
.player-team{font-size:.85rem;color:#9BA3B8}
.section-header{font-size:.9rem;font-weight:600;color:#C4A962;text-transform:uppercase;
                letter-spacing:1.5px;border-bottom:1px solid #2D3250;
                padding-bottom:5px;margin:14px 0 10px}
.divider{border-top:1px solid #2D3250;margin:16px 0}
.info-box{padding:10px 14px;background:#1A1D2E;border-radius:8px;
          border-left:3px solid #C4A962;font-size:.8rem;color:#9BA3B8;margin-top:6px}
#MainMenu,footer,header{visibility:hidden}
[data-testid="collapsedControl"]{color:#C4A962 !important;background-color:#1A1D2E !important;border-radius:0 6px 6px 0;opacity:1 !important;visibility:visible !important;transition:none !important}
</style>""", unsafe_allow_html=True)

# ── Cached data loaders ────────────────────────────────────────────────────────

MLB_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; MLBDashboard/1.0)"}

@st.cache_data(ttl=3600, show_spinner=False)
def load_mlb_hitting(seasons_tuple):
    """Season hitting stats for all players via MLB Stats API (never blocked)."""
    frames = []
    for season in seasons_tuple:
        url = (f"https://statsapi.mlb.com/api/v1/stats"
               f"?stats=season&group=hitting&gameType=R&season={season}"
               f"&sportId=1&limit=2000&offset=0")
        try:
            splits = requests.get(url, headers=MLB_HEADERS, timeout=20).json()\
                             .get("stats",[{}])[0].get("splits",[])
        except Exception as e:
            raise RuntimeError(f"MLB Stats API failed for {season}: {e}")
        rows = []
        for sp in splits:
            p = sp.get("player", {}); t = sp.get("team", {}); s = sp.get("stat", {})
            pa = int(s.get("plateAppearances", 0))
            if pa < 30: continue
            ab = int(s.get("atBats", 0)); h = int(s.get("hits", 0))
            bb = int(s.get("baseOnBalls", 0)); so = int(s.get("strikeOuts", 0))
            hr = int(s.get("homeRuns", 0))
            d2 = int(s.get("doubles", 0)); d3 = int(s.get("triples", 0))
            rows.append({
                "Name": p.get("fullName",""), "IDmlb": p.get("id"),
                "Team": t.get("name",""), "Season": season,
                "G": int(s.get("gamesPlayed",0)), "PA": pa, "AB": ab,
                "H": h, "2B": d2, "3B": d3, "HR": hr,
                "RBI": int(s.get("rbi",0)), "SB": int(s.get("stolenBases",0)),
                "BB": bb, "SO": so,
                "AVG": float(s.get("avg","0") or 0),
                "OBP": float(s.get("obp","0") or 0),
                "SLG": float(s.get("slg","0") or 0),
                "OPS": float(s.get("ops","0") or 0),
                "K%":  round(so/pa*100,1) if pa>0 else None,
                "BB%": round(bb/pa*100,1) if pa>0 else None,
            })
        if rows:
            frames.append(pd.DataFrame(rows))
    if not frames:
        raise RuntimeError("MLB Stats API returned no hitting data.")
    return pd.concat(frames, ignore_index=True)

@st.cache_data(ttl=3600, show_spinner=False)
def load_mlb_pitching(seasons_tuple):
    """Season pitching stats for all pitchers via MLB Stats API."""
    frames = []
    for season in seasons_tuple:
        url = (f"https://statsapi.mlb.com/api/v1/stats"
               f"?stats=season&group=pitching&gameType=R&season={season}"
               f"&sportId=1&limit=2000&offset=0")
        try:
            splits = requests.get(url, headers=MLB_HEADERS, timeout=20).json()\
                             .get("stats",[{}])[0].get("splits",[])
        except Exception as e:
            raise RuntimeError(f"MLB Stats API failed for {season}: {e}")
        rows = []
        for sp in splits:
            p = sp.get("player", {}); t = sp.get("team", {}); s = sp.get("stat", {})
            ip_raw = str(s.get("inningsPitched","0.0"))
            pts = ip_raw.split(".")
            ip = int(pts[0]) + (int(pts[1])/3 if len(pts)>1 and pts[1] else 0)
            if ip < 5: continue
            er = int(s.get("earnedRuns",0)); h_a = int(s.get("hits",0))
            bb = int(s.get("baseOnBalls",0)); so = int(s.get("strikeOuts",0))
            hr = int(s.get("homeRuns",0)); tbf = int(s.get("battersFaced",0))
            rows.append({
                "Name": p.get("fullName",""), "IDmlb": p.get("id"),
                "Team": t.get("name",""), "Season": season,
                "G": int(s.get("gamesPitched",0)), "GS": int(s.get("gamesStarted",0)),
                "W": int(s.get("wins",0)), "L": int(s.get("losses",0)),
                "SV": int(s.get("saves",0)), "IP": round(ip,1),
                "H": h_a, "ER": er, "HR": hr, "BB": bb, "SO": so,
                "ERA":  round(er/ip*9,2)      if ip>0  else None,
                "WHIP": round((h_a+bb)/ip,3)  if ip>0  else None,
                "K/9":  round(so/ip*9,1)      if ip>0  else None,
                "BB/9": round(bb/ip*9,1)      if ip>0  else None,
                "K%":   round(so/tbf*100,1)   if tbf>0 else None,
                "BB%":  round(bb/tbf*100,1)   if tbf>0 else None,
                "K-BB%":round((so-bb)/tbf*100,1) if tbf>0 else None,
                "HR/9": round(hr/ip*9,1)      if ip>0  else None,
            })
        if rows:
            frames.append(pd.DataFrame(rows))
    if not frames:
        raise RuntimeError("MLB Stats API returned no pitching data.")
    return pd.concat(frames, ignore_index=True)

@st.cache_data(ttl=7200, show_spinner=False)
def get_statcast_batter_raw(mlbam_id, season):
    if season not in SEASON_DATES: return pd.DataFrame()
    sd, ed = SEASON_DATES[season]
    try:
        df = statcast_batter(sd, ed, player_id=int(mlbam_id))
        if df is None or df.empty: return pd.DataFrame()
        df["game_date"] = pd.to_datetime(df["game_date"])
        df["Month_Num"] = df["game_date"].dt.month
        return df
    except Exception:
        return pd.DataFrame()

@st.cache_data(ttl=7200, show_spinner=False)
def get_statcast_pitcher_raw(mlbam_id, season):
    if season not in SEASON_DATES: return pd.DataFrame()
    sd, ed = SEASON_DATES[season]
    try:
        df = statcast_pitcher(sd, ed, player_id=int(mlbam_id))
        if df is None or df.empty: return pd.DataFrame()
        df["game_date"] = pd.to_datetime(df["game_date"])
        df["Month_Num"] = df["game_date"].dt.month
        return df
    except Exception:
        return pd.DataFrame()

@st.cache_data(ttl=7200, show_spinner=False)
def get_monthly_hitting_api(mlbam_id, season):
    url = (f"https://statsapi.mlb.com/api/v1/people/{mlbam_id}/stats"
           f"?stats=gameLog&season={season}&group=hitting&gameType=R&sportId=1")
    try:
        splits = requests.get(url, timeout=15).json().get("stats",[{}])[0].get("splits",[])
    except Exception:
        return pd.DataFrame()
    rows = []
    for sp in splits:
        try:
            m = pd.to_datetime(sp["date"]).month
            s = sp.get("stat", {})
            rows.append({"Month_Num":m, "Month":MONTH_NAMES.get(m,""),
                "G":int(s.get("gamesPlayed",0)), "PA":int(s.get("plateAppearances",0)),
                "AB":int(s.get("atBats",0)), "H":int(s.get("hits",0)),
                "2B":int(s.get("doubles",0)), "3B":int(s.get("triples",0)),
                "HR":int(s.get("homeRuns",0)), "RBI":int(s.get("rbi",0)),
                "SB":int(s.get("stolenBases",0)), "BB":int(s.get("baseOnBalls",0)),
                "SO":int(s.get("strikeOuts",0))})
        except Exception:
            continue
    if not rows: return pd.DataFrame()
    agg = pd.DataFrame(rows).groupby(["Month_Num","Month"]).sum(numeric_only=True).reset_index()
    agg["AVG"] = (agg["H"]/agg["AB"]).where(agg["AB"]>0).round(3)
    agg["OBP"] = ((agg["H"]+agg["BB"])/agg["PA"]).where(agg["PA"]>0).round(3)
    tb = agg["H"] + agg["2B"] + 2*agg["3B"] + 3*agg["HR"]
    agg["SLG"] = (tb/agg["AB"]).where(agg["AB"]>0).round(3)
    agg["OPS"] = (agg["OBP"] + agg["SLG"]).round(3)
    return agg.sort_values("Month_Num")

@st.cache_data(ttl=7200, show_spinner=False)
def get_monthly_pitching_api(mlbam_id, season):
    url = (f"https://statsapi.mlb.com/api/v1/people/{mlbam_id}/stats"
           f"?stats=gameLog&season={season}&group=pitching&gameType=R&sportId=1")
    try:
        splits = requests.get(url, timeout=15).json().get("stats",[{}])[0].get("splits",[])
    except Exception:
        return pd.DataFrame()
    rows = []
    for sp in splits:
        try:
            m = pd.to_datetime(sp["date"]).month
            s = sp.get("stat", {})
            ip_str = str(s.get("inningsPitched","0.0"))
            p = ip_str.split(".")
            ip = int(p[0]) + (int(p[1])/3 if len(p)>1 else 0)
            rows.append({"Month_Num":m, "Month":MONTH_NAMES.get(m,""),
                "G":int(s.get("gamesPlayed",0)), "GS":int(s.get("gamesStarted",0)),
                "IP":ip, "ER":int(s.get("earnedRuns",0)),
                "H":int(s.get("hits",0)), "HR":int(s.get("homeRuns",0)),
                "BB":int(s.get("baseOnBalls",0)), "SO":int(s.get("strikeOuts",0))})
        except Exception:
            continue
    if not rows: return pd.DataFrame()
    agg = pd.DataFrame(rows).groupby(["Month_Num","Month"]).sum(numeric_only=True).reset_index()
    agg["ERA"]  = (agg["ER"]/agg["IP"]*9).where(agg["IP"]>0).round(2)
    agg["WHIP"] = ((agg["H"]+agg["BB"])/agg["IP"]).where(agg["IP"]>0).round(3)
    agg["K/9"]  = (agg["SO"]/agg["IP"]*9).where(agg["IP"]>0).round(1)
    agg["BB/9"] = (agg["BB"]/agg["IP"]*9).where(agg["IP"]>0).round(1)
    return agg.sort_values("Month_Num")

def agg_statcast_hit_monthly(sc):
    if sc.empty: return pd.DataFrame()
    rows = []
    for m, grp in sc.groupby("Month_Num"):
        ev   = grp["launch_speed"].dropna()
        xba  = grp["estimated_ba_using_speedangle"].dropna() if "estimated_ba_using_speedangle" in grp else pd.Series(dtype=float)
        xwoba= grp["estimated_woba_using_speedangle"].dropna() if "estimated_woba_using_speedangle" in grp else pd.Series(dtype=float)
        bip  = grp[grp["type"]=="X"]
        swstr= grp[grp["description"].isin(["swinging_strike","swinging_strike_blocked"])]
        oz   = grp[grp["zone"].isin([11,12,13,14])] if "zone" in grp.columns else pd.DataFrame()
        chase= oz[oz["description"].isin(["swinging_strike","swinging_strike_blocked","foul","hit_into_play"])] if not oz.empty else pd.DataFrame()
        iz   = grp[grp["zone"].between(1,9)] if "zone" in grp.columns else pd.DataFrame()
        zsw  = iz[iz["description"].isin(["swinging_strike","swinging_strike_blocked","foul","hit_into_play"])] if not iz.empty else pd.DataFrame()
        zcnt = iz[iz["description"].isin(["foul","hit_into_play"])] if not iz.empty else pd.DataFrame()
        rows.append({
            "Month": MONTH_NAMES.get(m, str(m)), "Month_Num": m,
            "xBA":       round(xba.mean(),3)  if len(xba)>0  else None,
            "xwOBA":     round(xwoba.mean(),3) if len(xwoba)>0 else None,
            "EV_avg":    round(ev.mean(),1)   if len(ev)>0   else None,
            "HardHit_pct": round((ev>=95).sum()/len(ev)*100,1) if len(ev)>0 else None,
            "SwStr_pct": round(len(swstr)/len(grp)*100,1) if len(grp)>0 else None,
            "Chase_pct": round(len(chase)/len(oz)*100,1)  if len(oz)>0  else None,
            "ZContact_pct": round(len(zcnt)/len(zsw)*100,1) if len(zsw)>0 else None,
        })
    return pd.DataFrame(rows).sort_values("Month_Num")

def agg_statcast_pitch_monthly(sc):
    if sc.empty: return pd.DataFrame()
    rows = []
    for m, grp in sc.groupby("Month_Num"):
        ev   = grp["launch_speed"].dropna()
        bip  = grp[grp["type"]=="X"]
        velo = grp["release_speed"].dropna()
        spin = grp["release_spin_rate"].dropna() if "release_spin_rate" in grp else pd.Series(dtype=float)
        swstr= grp[grp["description"].isin(["swinging_strike","swinging_strike_blocked"])]
        rows.append({
            "Month": MONTH_NAMES.get(m, str(m)), "Month_Num": m,
            "EV_avg":    round(ev.mean(),1)   if len(ev)>0   else None,
            "HardHit_pct": round((ev>=95).sum()/len(ev)*100,1) if len(ev)>0 else None,
            "Velo_avg":  round(velo.mean(),1) if len(velo)>0 else None,
            "Spin_avg":  round(spin.mean(),0) if len(spin)>0 else None,
            "SwStr_pct": round(len(swstr)/len(grp)*100,1) if len(grp)>0 else None,
        })
    return pd.DataFrame(rows).sort_values("Month_Num")

def build_arsenal(sc):
    if sc.empty or "pitch_type" not in sc.columns: return pd.DataFrame()
    sc = sc[sc["pitch_type"].notna() & (sc["pitch_type"]!="")]
    agg = sc.groupby("pitch_type").agg(
        Count=("pitch_type","count"),
        Velo=("release_speed","mean"),
        Spin=("release_spin_rate","mean"),
        xwOBA=("estimated_woba_using_speedangle","mean"),
    ).reset_index()
    total = agg["Count"].sum()
    agg["Usage%"] = (agg["Count"]/total*100).round(1)
    agg["Velo"]   = agg["Velo"].round(1)
    agg["Spin"]   = agg["Spin"].round(0)
    agg["xwOBA"]  = agg["xwOBA"].round(3)
    agg["Pitch"]  = agg["pitch_type"].map(PITCH_NAMES).fillna(agg["pitch_type"])
    return agg.sort_values("Usage%", ascending=False)

# ── Sidebar ────────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("## MLB Comparison")
    mode = st.radio("Compare", ["Hitters","Pitchers"], horizontal=True)
    sel_seasons = st.multiselect("Seasons", ALL_SEASONS, default=[2024,2025,2026])
    if not sel_seasons:
        sel_seasons = [2025]
    seasons_key = tuple(sorted(sel_seasons))
    st.markdown("---")

    loader_label = "Loading hitter list..." if mode=="Hitters" else "Loading pitcher list..."
    all_fg = pd.DataFrame()
    load_error = None
    with st.spinner(loader_label):
        try:
            all_fg = load_mlb_hitting(seasons_key) if mode=="Hitters" else load_mlb_pitching(seasons_key)
        except Exception as e:
            load_error = str(e)

    if all_fg.empty or load_error:
        st.error("Could not load player list.")
        st.code(load_error or "No data returned.", language=None)
        st.stop()

    sort_col = "OPS" if (mode=="Hitters" and "OPS" in all_fg.columns) else \
               "ERA" if (mode=="Pitchers" and "ERA" in all_fg.columns) else "Name"
    sort_asc  = mode == "Pitchers"
    player_list = (all_fg.sort_values("Season", ascending=False)
                         .drop_duplicates("Name")
                         .sort_values(sort_col, ascending=sort_asc)["Name"]
                         .tolist())

    if len(player_list) < 2:
        st.error("Not enough players. Try different seasons.")
        st.stop()

    def_a = next((p for p in player_list if "Lee" in p and "Jung" in p), player_list[0])
    def_b = next((p for p in player_list if "Rafaela" in p), player_list[1])

    player_a = st.selectbox("Player A", player_list,
                            index=player_list.index(def_a) if def_a in player_list else 0)
    pb_opts = [p for p in player_list if p != player_a]
    def_b_i = pb_opts.index(def_b) if def_b in pb_opts else 0
    player_b = st.selectbox("Player B", pb_opts, index=def_b_i)

    st.markdown("---")
    st.caption("FanGraphs · Baseball Savant · MLB Stats API · pybaseball 2.2.7")

PLAYERS = [player_a, player_b]
COLORS  = {player_a: PA_COL, player_b: PB_COL}

# ── Helper: pull player row from FG ───────────────────────────────────────────
def p_seasons(name): return all_fg[all_fg["Name"]==name].sort_values("Season")
def p_latest(name):
    d = p_seasons(name); return d.iloc[-1] if not d.empty else None
def p_mlbam(name):
    r = p_latest(name)
    return int(r["IDmlb"]) if r is not None and "IDmlb" in r.index and pd.notna(r.get("IDmlb")) else None
def safe(val, fmt="{:.3f}"):
    try: return fmt.format(float(val)) if val is not None and pd.notna(val) else "N/A"
    except: return "N/A"

# ── Header ─────────────────────────────────────────────────────────────────────
st.markdown(f"""
<div style="font-size:2rem;font-weight:800;color:#FAFAFA;text-align:center;margin-bottom:4px">
  MLB Player Comparison
</div>
<div style="font-size:.9rem;color:#9BA3B8;text-align:center;margin-bottom:18px">
  {player_a} vs. {player_b} &nbsp;·&nbsp; {mode} &nbsp;·&nbsp; {", ".join(str(s) for s in sorted(sel_seasons))}
</div>""", unsafe_allow_html=True)

hcols = st.columns([1, 0.08, 1])
for col_w, player in zip([hcols[0], hcols[2]], PLAYERS):
    color   = COLORS[player]
    mlbam   = p_mlbam(player)
    row     = p_latest(player)
    team    = row["Team"] if row is not None and "Team" in row.index else "MLB"
    hs_url  = (f"https://img.mlbstatic.com/mlb-photos/image/upload/"
               f"d_people:generic:headshot:67:current.png"
               f"/w_213,q_auto:best/v1/people/{mlbam}/headshot/67/current") if mlbam else ""
    img_tag = (f'<img src="{hs_url}" width="95" '
               f'style="border-radius:50%;border:3px solid {color};" '
               f'onerror="this.style.display=\'none\'"/>') if hs_url else ""
    with col_w:
        st.markdown(f"""
        <div class="player-card" style="border-top-color:{color}">
          {img_tag}
          <div class="player-name">{player}</div>
          <div class="player-team">{team}</div>
        </div>""", unsafe_allow_html=True)

# MLBAM IDs come directly from MLB Stats API — no reverse lookup needed
mlbam_ids = {p: p_mlbam(p) for p in PLAYERS}

# ── Tabs ───────────────────────────────────────────────────────────────────────
if mode == "Hitters":
    t1,t2,t3,t4,t5 = st.tabs(["Overview","Hitting","Statcast","Plate Discipline","Defense"])
else:
    t1,t2,t3,t4,t5 = st.tabs(["Overview","Results","Arsenal","Batted Ball","Advanced"])

# ════════════════════════════════════════════════════════════════════════════════
# SHARED: performance index bar (used in both Overview tabs)
# ════════════════════════════════════════════════════════════════════════════════
def perf_index_bar(metrics, avgs, title):
    """metrics = [(label, col, display_fmt, lower_is_better), ...]"""
    fig = go.Figure()
    for player in PLAYERS:
        idx_vals, txt_vals = [], []
        for label, col, fmt, lower in metrics:
            s = p_seasons(player)
            v = s[col].iloc[-1] if not s.empty and col in s.columns and pd.notna(s[col].iloc[-1]) else None
            if v is not None and col in avgs and avgs[col]:
                idx = (avgs[col]/v*100) if lower else (v/avgs[col]*100)
                idx_vals.append(round(idx,1))
                txt_vals.append(fmt.format(float(v)))
            else:
                idx_vals.append(None); txt_vals.append("N/A")
        fig.add_trace(go.Bar(
            y=[m[0] for m in metrics], x=idx_vals, name=player,
            orientation="h", marker_color=COLORS[player],
            text=txt_vals, textposition="outside",
            textfont=dict(color=TEXT, size=10),
            hovertemplate="<b>%{y}</b><br>"+player+": %{text}<br>Index: %{x:.0f}<extra></extra>",
        ))
    fig.add_vline(x=100, line_color=GOLD, line_dash="dash", line_width=2)
    fig.add_annotation(x=100, y=len(metrics)-0.5, text="MLB Avg",
                       showarrow=False, font=dict(color=GOLD,size=10),
                       xanchor="left", xshift=4)
    apply_layout(fig, barmode="group", height=max(320, len(metrics)*52),
                 title=title,
                 xaxis=dict(range=[40,175], gridcolor=LINE_CLR, title="Index (100 = MLB Avg)"),
                 legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1))
    return fig

def season_bar(col, title, ref_val, ref_label, y_title, fmt="{:.3f}", height=340):
    fig = go.Figure()
    for player in PLAYERS:
        s = p_seasons(player).dropna(subset=[col])
        if s.empty: continue
        fig.add_trace(go.Bar(
            x=s["Season"].astype(str), y=s[col], name=player,
            marker_color=COLORS[player],
            text=s[col].apply(lambda v: fmt.format(float(v))),
            textposition="outside", textfont=dict(color=TEXT,size=11),
        ))
    if ref_val:
        fig.add_hline(y=ref_val, line_dash="dash", line_color=GOLD,
                      annotation_text=ref_label, annotation_font_color=GOLD,
                      annotation_position="top right")
    apply_layout(fig, barmode="group", height=height, title=title,
                 yaxis_title=y_title,
                 legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1))
    return fig

def monthly_line(monthly_dict, col, title, ref_val, ref_label, y_title, sel_season):
    fig = go.Figure()
    for player in PLAYERS:
        df = monthly_dict.get(player, pd.DataFrame())
        if df.empty or col not in df.columns: continue
        s = df.dropna(subset=[col]).sort_values("Month_Num")
        fig.add_trace(go.Scatter(
            x=s["Month"], y=s[col], mode="lines+markers", name=player,
            line=dict(color=COLORS[player], width=2.5), marker=dict(size=7),
            hovertemplate="%{x}: %{y}<extra>"+player+"</extra>",
        ))
    if ref_val:
        fig.add_hline(y=ref_val, line_dash="dot", line_color=GOLD,
                      annotation_text=ref_label, annotation_font_color=GOLD)
    apply_layout(fig, title=title, yaxis_title=y_title,
                 legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1))
    return fig

# ════════════════════════════════════════════════════════════════════════════════
# TAB 1 — OVERVIEW (both modes)
# ════════════════════════════════════════════════════════════════════════════════
with t1:
    if mode == "Hitters":
        hit_metrics = [
            ("AVG",    "AVG",   "{:.3f}", False),
            ("OBP",    "OBP",   "{:.3f}", False),
            ("SLG",    "SLG",   "{:.3f}", False),
            ("OPS",    "OPS",   "{:.3f}", False),
            ("BB %",   "BB%",   "{:.1f}%",False),
            ("K % (lower=better)","K%","{:.1f}%",True),
        ]
        st.markdown('<div class="section-header">Latest Season Performance Index</div>', unsafe_allow_html=True)
        st.plotly_chart(perf_index_bar(hit_metrics, HIT_AVG,
                        "Latest Season Stats vs. MLB Average — 100 = League Average"),
                        use_container_width=True)
        st.markdown('<div class="divider"></div>', unsafe_allow_html=True)
        st.plotly_chart(season_bar("OPS","OPS by Season",0.720,"MLB Avg (.720)","OPS"), use_container_width=True)

    else:  # Pitchers
        pit_metrics = [
            ("ERA (lower=better)", "ERA",   "{:.2f}", True),
            ("WHIP (lower=better)","WHIP",  "{:.3f}", True),
            ("K %",   "K%",    "{:.1f}%", False),
            ("BB % (lower=better)","BB%",  "{:.1f}%", True),
            ("K-BB %","K-BB%", "{:.1f}%", False),
            ("K/9",   "K/9",   "{:.1f}",  False),
            ("BB/9 (lower=better)","BB/9", "{:.1f}",  True),
        ]
        st.markdown('<div class="section-header">Latest Season Performance Index</div>', unsafe_allow_html=True)
        st.plotly_chart(perf_index_bar(pit_metrics, PIT_AVG,
                        "Latest Season Pitching Index vs. MLB Average — 100 = League Average"),
                        use_container_width=True)
        st.markdown('<div class="divider"></div>', unsafe_allow_html=True)
        st.plotly_chart(season_bar("ERA","ERA by Season",4.20,"MLB Avg (4.20)","ERA","{:.2f}"), use_container_width=True)

    # Scouting grades (if available for selected players)
    has_grades = any(p in SCOUTING for p in PLAYERS)
    if has_grades:
        st.markdown('<div class="divider"></div>', unsafe_allow_html=True)
        st.markdown('<div class="section-header">Scouting Tool Grades — 20-80 Scale (FanGraphs)</div>', unsafe_allow_html=True)
        tools = ["Hit","Power","Speed","Field","Arm"] if mode=="Hitters" else ["FB Velo","Command","Stamina","Deception","Arm Strength"]
        fig_g = go.Figure()
        for player in PLAYERS:
            if player not in SCOUTING: continue
            grades = [SCOUTING[player].get(t,50) for t in tools]
            fig_g.add_trace(go.Bar(
                y=tools, x=grades, name=player, orientation="h",
                marker_color=COLORS[player],
                text=[f"{g} — {grade_label(g)}" for g in grades],
                textposition="outside", textfont=dict(color=TEXT,size=10),
                hovertemplate="<b>%{y}</b><br>"+player+": %{x}/80<extra></extra>",
            ))
        for x0,x1,c in [(20,40,"rgba(231,76,60,.08)"),(40,50,"rgba(230,126,34,.08)"),
                        (50,60,"rgba(196,169,98,.08)"),(60,80,"rgba(46,204,113,.08)")]:
            fig_g.add_vrect(x0=x0,x1=x1,fillcolor=c,line_width=0,layer="below")
        fig_g.add_vline(x=50,line_color=GOLD,line_dash="dash",line_width=1.5)
        apply_layout(fig_g, barmode="group", height=320,
                     title="Tool Grades — Source: FanGraphs Scouting Reports",
                     xaxis=dict(range=[20,98],gridcolor=LINE_CLR,
                                tickvals=[20,30,40,50,60,70,80],
                                title="Grade (20=Poor · 50=Avg · 80=Elite)"),
                     legend=dict(orientation="h",yanchor="bottom",y=1.02,xanchor="right",x=1))
        st.plotly_chart(fig_g, use_container_width=True)
        st.markdown("""<div class="info-box">
        <b style="color:#C4A962">20-80 Scale:</b> &nbsp;
        20=Poor &nbsp;·&nbsp; 40=Below Avg &nbsp;·&nbsp; 50=Average &nbsp;·&nbsp;
        55=Above Avg &nbsp;·&nbsp; 60=Plus &nbsp;·&nbsp; 70=Well Above Avg &nbsp;·&nbsp; 80=Elite
        </div>""", unsafe_allow_html=True)

# ════════════════════════════════════════════════════════════════════════════════
# HITTER TABS 2-5
# ════════════════════════════════════════════════════════════════════════════════
if mode == "Hitters":

    # ── TAB 2: HITTING ─────────────────────────────────────────────────────────
    with t2:
        sel_s = st.selectbox("Season", sorted(sel_seasons, reverse=True), key="hit_s")
        st.markdown('<div class="section-header">Monthly Hitting Trends</div>', unsafe_allow_html=True)

        if not any(mlbam_ids.values()):
            st.warning("Could not resolve MLB IDs for selected players.")
        else:
            monthly_hit = {}
            for p in PLAYERS:
                mid = mlbam_ids[p]
                if mid:
                    with st.spinner(f"Loading monthly hitting data for {p}..."):
                        monthly_hit[p] = get_monthly_hitting_api(mid, sel_s)
                else:
                    monthly_hit[p] = pd.DataFrame()

            c1,c2 = st.columns(2)
            with c1:
                st.plotly_chart(monthly_line(monthly_hit,"AVG","AVG by Month",
                    0.248,"MLB Avg (.248)","AVG",sel_s), use_container_width=True)
            with c2:
                st.plotly_chart(monthly_line(monthly_hit,"OPS","OPS by Month",
                    0.720,"MLB Avg (.720)","OPS",sel_s), use_container_width=True)
            c3,c4 = st.columns(2)
            with c3:
                st.plotly_chart(monthly_line(monthly_hit,"HR","Home Runs by Month",
                    None,None,"HR",sel_s), use_container_width=True)
            with c4:
                st.plotly_chart(monthly_line(monthly_hit,"OBP","OBP by Month",
                    0.320,"MLB Avg (.320)","OBP",sel_s), use_container_width=True)

        st.markdown('<div class="divider"></div>', unsafe_allow_html=True)
        st.markdown('<div class="section-header">Season Totals</div>', unsafe_allow_html=True)
        disp_cols = ["Name","Season","G","PA","AB","H","AVG","OBP","SLG","OPS","HR","RBI","SB","BB","SO","K%","BB%"]
        avail = [c for c in disp_cols if c in all_fg.columns]
        tbl = pd.concat([p_seasons(p) for p in PLAYERS])[avail].sort_values(["Name","Season"])
        fmt_map = {c:"{:.3f}" for c in ["AVG","OBP","SLG","OPS"]}
        fmt_map.update({c:"{:.1f}" for c in ["K%","BB%"]})
        st.dataframe(tbl.style.format(fmt_map, na_rep="N/A")
                              .background_gradient(subset=[c for c in ["AVG","OBP","SLG","OPS"] if c in tbl.columns], cmap="RdYlGn"),
                     use_container_width=True, hide_index=True)

    # ── TAB 3: STATCAST ────────────────────────────────────────────────────────
    with t3:
        sel_s3 = st.selectbox("Season", sorted(sel_seasons, reverse=True), key="sc_s")
        st.info("Statcast data may take 20-60 seconds to load on first access. Results are cached for 2 hours.")

        sc_monthly = {}
        for p in PLAYERS:
            mid = mlbam_ids[p]
            if mid:
                with st.spinner(f"Loading Statcast for {p} ({sel_s3})..."):
                    raw = get_statcast_batter_raw(mid, sel_s3)
                    sc_monthly[p] = agg_statcast_hit_monthly(raw)
            else:
                sc_monthly[p] = pd.DataFrame()

        st.markdown('<div class="section-header">Exit Velocity & Expected Stats by Month</div>', unsafe_allow_html=True)
        c1,c2 = st.columns(2)
        with c1:
            st.plotly_chart(monthly_line(sc_monthly,"EV_avg","Avg Exit Velocity by Month",
                88.5,"MLB Avg 88.5","mph",sel_s3), use_container_width=True)
        with c2:
            st.plotly_chart(monthly_line(sc_monthly,"xBA","xBA by Month",
                0.248,"MLB Avg (.248)","xBA",sel_s3), use_container_width=True)
        c3,c4 = st.columns(2)
        with c3:
            st.plotly_chart(monthly_line(sc_monthly,"HardHit_pct","Hard Hit % by Month",
                37.5,"MLB Avg 37.5%","Hard Hit %",sel_s3), use_container_width=True)
        with c4:
            st.plotly_chart(monthly_line(sc_monthly,"xwOBA","xwOBA by Month",
                0.317,"MLB Avg (.317)","xwOBA",sel_s3), use_container_width=True)

        st.markdown('<div class="divider"></div>', unsafe_allow_html=True)
        st.markdown('<div class="section-header">Exit Velocity & Hard Hit % — Career by Season</div>', unsafe_allow_html=True)
        c5,c6 = st.columns(2)
        with c5:
            # Aggregate from Statcast across all selected seasons
            frames = []
            for p in PLAYERS:
                mid = mlbam_ids[p]
                if not mid: continue
                for s in sel_seasons:
                    with st.spinner(f"Loading {p} {s}..."):
                        raw = get_statcast_batter_raw(mid, s)
                    if raw.empty: continue
                    ev = raw["launch_speed"].dropna()
                    frames.append({"Player":p,"Season":s,
                        "EV_avg": round(ev.mean(),1) if len(ev)>0 else None,
                        "HardHit_pct": round((ev>=95).sum()/len(ev)*100,1) if len(ev)>0 else None,
                    })
            if frames:
                sc_career = pd.DataFrame(frames)
                fig_ev = go.Figure()
                for p in PLAYERS:
                    sub = sc_career[sc_career["Player"]==p].dropna(subset=["EV_avg"])
                    fig_ev.add_trace(go.Bar(x=sub["Season"].astype(str), y=sub["EV_avg"],
                        name=p, marker_color=COLORS[p],
                        text=sub["EV_avg"].round(1), textposition="outside",
                        textfont=dict(color=TEXT,size=11)))
                fig_ev.add_hline(y=88.5,line_dash="dash",line_color=GOLD,
                                 annotation_text="MLB Avg",annotation_font_color=GOLD,
                                 annotation_position="top right")
                apply_layout(fig_ev, barmode="group", title="Avg Exit Velocity by Season",
                             yaxis_title="mph",
                             legend=dict(orientation="h",yanchor="bottom",y=1.02,xanchor="right",x=1))
                c5.plotly_chart(fig_ev, use_container_width=True)
                fig_hh = go.Figure()
                for p in PLAYERS:
                    sub = sc_career[sc_career["Player"]==p].dropna(subset=["HardHit_pct"])
                    fig_hh.add_trace(go.Bar(x=sub["Season"].astype(str), y=sub["HardHit_pct"],
                        name=p, marker_color=COLORS[p],
                        text=sub["HardHit_pct"].round(1), textposition="outside",
                        textfont=dict(color=TEXT,size=11)))
                fig_hh.add_hline(y=37.5,line_dash="dash",line_color=GOLD,
                                 annotation_text="MLB Avg",annotation_font_color=GOLD,
                                 annotation_position="top right")
                apply_layout(fig_hh, barmode="group", title="Hard Hit % by Season",
                             yaxis_title="%",
                             legend=dict(orientation="h",yanchor="bottom",y=1.02,xanchor="right",x=1))
                c6.plotly_chart(fig_hh, use_container_width=True)

    # ── TAB 4: PLATE DISCIPLINE ────────────────────────────────────────────────
    with t4:
        sel_s4 = st.selectbox("Season", sorted(sel_seasons, reverse=True), key="pd_s")
        st.markdown('<div class="section-header">Season Totals — MLB Stats API</div>', unsafe_allow_html=True)

        disc_cols = ["Name","Season","BB%","K%","SwStr%","O-Swing%","Z-Contact%","Contact%","Zone%"]
        avail_d = [c for c in disc_cols if c in all_fg.columns]
        disc_tbl = pd.concat([p_seasons(p) for p in PLAYERS])[avail_d].sort_values(["Name","Season"])
        st.dataframe(disc_tbl.style.format({c:"{:.1f}" for c in avail_d if c not in ["Name","Season"]}, na_rep="N/A")
                                   .background_gradient(subset=[c for c in ["BB%","Z-Contact%","Contact%"] if c in disc_tbl.columns], cmap="RdYlGn")
                                   .background_gradient(subset=[c for c in ["K%","O-Swing%","SwStr%"] if c in disc_tbl.columns], cmap="RdYlGn_r"),
                     use_container_width=True, hide_index=True)

        st.markdown('<div class="divider"></div>', unsafe_allow_html=True)
        st.markdown('<div class="section-header">Monthly Discipline from Statcast</div>', unsafe_allow_html=True)
        st.info("Loading Statcast monthly discipline data...")

        sc_disc = {}
        for p in PLAYERS:
            mid = mlbam_ids[p]
            if mid:
                with st.spinner(f"Loading Statcast for {p}..."):
                    raw = get_statcast_batter_raw(mid, sel_s4)
                    sc_disc[p] = agg_statcast_hit_monthly(raw)
            else:
                sc_disc[p] = pd.DataFrame()

        c1,c2 = st.columns(2)
        with c1:
            st.plotly_chart(monthly_line(sc_disc,"Chase_pct","Chase Rate by Month (lower=better)",
                30.0,"MLB Avg 30%","Chase %",sel_s4), use_container_width=True)
        with c2:
            st.plotly_chart(monthly_line(sc_disc,"SwStr_pct","Swinging Strike % by Month (lower=better)",
                10.8,"MLB Avg 10.8%","SwStr %",sel_s4), use_container_width=True)
        c3,c4 = st.columns(2)
        with c3:
            st.plotly_chart(monthly_line(sc_disc,"ZContact_pct","Zone Contact % by Month (higher=better)",
                84.0,"MLB Avg 84%","Z-Contact %",sel_s4), use_container_width=True)
        with c4:
            # BB% and K% from FanGraphs season data — show by season bar
            st.plotly_chart(season_bar("BB%","Walk Rate by Season (%)",
                8.5,"MLB Avg 8.5%","BB %","{:.1f}"), use_container_width=True)

    # ── TAB 5: DEFENSE ─────────────────────────────────────────────────────────
    with t5:
        st.markdown('<div class="section-header">Defensive Value</div>', unsafe_allow_html=True)
        st.info("Detailed defensive metrics (OAA, UZR, DRS, Def) are not available from the MLB Stats API. "
                "Check the links below for full defensive leaderboards.")

        st.markdown('<div class="divider"></div>', unsafe_allow_html=True)
        st.markdown("""<div class="info-box">
        <b style="color:#C4A962">Note on OAA / UZR:</b> Outs Above Average and UZR require individual
        Baseball Savant lookups. For players other than Jung Hoo Lee and Ceddanne Rafaela,
        check <a href="https://baseballsavant.mlb.com/leaderboard/outs_above_average" target="_blank"
        style="color:#C4A962">Baseball Savant OAA Leaderboard</a> for full defensive metrics.
        </div>""", unsafe_allow_html=True)

# ════════════════════════════════════════════════════════════════════════════════
# PITCHER TABS 2-5
# ════════════════════════════════════════════════════════════════════════════════
else:

    # ── TAB 2: RESULTS ─────────────────────────────────────────────────────────
    with t2:
        sel_s2 = st.selectbox("Season", sorted(sel_seasons, reverse=True), key="res_s")
        st.markdown('<div class="section-header">Monthly ERA & WHIP Trends</div>', unsafe_allow_html=True)

        st.info("Loading monthly pitching data from MLB Stats API...")
        monthly_pit = {}
        for p in PLAYERS:
            mid = mlbam_ids[p]
            if mid:
                with st.spinner(f"Loading monthly pitching for {p}..."):
                    monthly_pit[p] = get_monthly_pitching_api(mid, sel_s2)
            else:
                monthly_pit[p] = pd.DataFrame()

        c1,c2 = st.columns(2)
        with c1:
            st.plotly_chart(monthly_line(monthly_pit,"ERA","ERA by Month",
                4.20,"MLB Avg (4.20)","ERA",sel_s2), use_container_width=True)
        with c2:
            st.plotly_chart(monthly_line(monthly_pit,"WHIP","WHIP by Month",
                1.28,"MLB Avg (1.28)","WHIP",sel_s2), use_container_width=True)
        c3,c4 = st.columns(2)
        with c3:
            st.plotly_chart(monthly_line(monthly_pit,"K/9","K/9 by Month",
                9.0,"MLB Avg (9.0)","K/9",sel_s2), use_container_width=True)
        with c4:
            st.plotly_chart(monthly_line(monthly_pit,"BB/9","BB/9 by Month (lower=better)",
                3.1,"MLB Avg (3.1)","BB/9",sel_s2), use_container_width=True)

        st.markdown('<div class="divider"></div>', unsafe_allow_html=True)
        st.markdown('<div class="section-header">Career Season Totals</div>', unsafe_allow_html=True)
        p_cols = ["Name","Season","G","GS","IP","W","L","SV","ERA","WHIP","K/9","BB/9","K%","BB%","K-BB%","HR/9"]
        avail_p = [c for c in p_cols if c in all_fg.columns]
        p_tbl = pd.concat([p_seasons(p) for p in PLAYERS])[avail_p].sort_values(["Name","Season"])
        pfmt = {c:"{:.2f}" for c in ["ERA","WHIP"]}
        pfmt.update({c:"{:.1f}" for c in ["IP","K/9","BB/9","K%","BB%","K-BB%","HR/9"]})
        st.dataframe(p_tbl.style.format(pfmt, na_rep="N/A")
                               .background_gradient(subset=[c for c in ["ERA","WHIP"] if c in p_tbl.columns], cmap="RdYlGn_r")
                               .background_gradient(subset=[c for c in ["K%","K-BB%","K/9"] if c in p_tbl.columns], cmap="RdYlGn"),
                     use_container_width=True, hide_index=True)

    # ── TAB 3: ARSENAL ─────────────────────────────────────────────────────────
    with t3:
        sel_s3p = st.selectbox("Season", sorted(sel_seasons, reverse=True), key="ars_s")
        st.info("Pulling pitch-level Statcast data. First load takes 20-60 seconds and is then cached.")

        for player in PLAYERS:
            mid = mlbam_ids[player]
            if not mid:
                st.warning(f"No MLBAM ID found for {player}.")
                continue
            with st.spinner(f"Loading arsenal for {player} ({sel_s3p})..."):
                raw_p = get_statcast_pitcher_raw(mid, sel_s3p)
            ars = build_arsenal(raw_p)
            if ars.empty:
                st.info(f"No pitch data found for {player} in {sel_s3p}.")
                continue

            color = COLORS[player]
            st.markdown(f'<div class="section-header" style="color:{color}">{player} — Pitch Arsenal</div>', unsafe_allow_html=True)
            ca1, ca2 = st.columns([1,1])

            with ca1:
                # Usage pie
                fig_pie = go.Figure(go.Pie(
                    labels=ars["Pitch"], values=ars["Usage%"],
                    marker_colors=[color,"#4A5568","#718096","#A0AEC0","#CBD5E0","#E2E8F0"][:len(ars)],
                    textinfo="label+percent", hole=0.35,
                ))
                fig_pie.update_layout(
                    paper_bgcolor=CARD_BG, font=dict(color=TEXT,family="Segoe UI"),
                    margin=dict(l=10,r=10,t=40,b=10), height=300,
                    title=dict(text="Pitch Usage %",font=dict(color=TEXT)),
                    showlegend=False,
                )
                ca1.plotly_chart(fig_pie, use_container_width=True)

            with ca2:
                # Velocity bar
                fig_velo = go.Figure(go.Bar(
                    y=ars["Pitch"], x=ars["Velo"], orientation="h",
                    marker_color=color,
                    text=ars["Velo"].apply(lambda v: f"{v:.1f} mph"),
                    textposition="outside", textfont=dict(color=TEXT,size=11),
                ))
                apply_layout(fig_velo, title="Avg Velocity by Pitch Type",
                             xaxis=dict(range=[60,105],gridcolor=LINE_CLR,title="mph"),
                             height=300)
                ca2.plotly_chart(fig_velo, use_container_width=True)

            # Arsenal table
            disp_ars = ars[["Pitch","Usage%","Velo","Spin","xwOBA"]].rename(
                columns={"Usage%":"Usage %","Velo":"Avg Velo (mph)","Spin":"Avg Spin (rpm)"})
            st.dataframe(
                disp_ars.style.format({"Usage %":"{:.1f}","Avg Velo (mph)":"{:.1f}",
                                       "Avg Spin (rpm)":"{:.0f}","xwOBA":"{:.3f}"}, na_rep="N/A")
                               .background_gradient(subset=["xwOBA"], cmap="RdYlGn_r"),
                use_container_width=True, hide_index=True)
            st.markdown('<div class="divider"></div>', unsafe_allow_html=True)

    # ── TAB 4: BATTED BALL ─────────────────────────────────────────────────────
    with t4:
        st.markdown('<div class="section-header">Batted Ball Profile — Season Totals</div>', unsafe_allow_html=True)
        bb_cols = ["Name","Season","HR","HR/9","ERA","WHIP","K%","BB%","K-BB%"]
        avail_bb = [c for c in bb_cols if c in all_fg.columns]
        bb_tbl = pd.concat([p_seasons(p) for p in PLAYERS])[avail_bb].sort_values(["Name","Season"])
        st.dataframe(
            bb_tbl.style.format({c:"{:.2f}" for c in ["ERA","WHIP"]}
                                | {c:"{:.1f}" for c in ["HR/9","K%","BB%","K-BB%"]}, na_rep="N/A")
                        .background_gradient(subset=[c for c in ["K%","K-BB%"] if c in bb_tbl.columns], cmap="RdYlGn")
                        .background_gradient(subset=[c for c in ["ERA","WHIP","HR/9"] if c in bb_tbl.columns], cmap="RdYlGn_r"),
            use_container_width=True, hide_index=True)
        st.info("GB%, FB%, LD%, Hard% are FanGraphs metrics not available from MLB Stats API. "
                "See Baseball Savant for detailed batted ball profiles.")

        st.markdown('<div class="divider"></div>', unsafe_allow_html=True)
        c1,c2 = st.columns(2)
        with c1:
            st.plotly_chart(season_bar("HR/9","HR/9 by Season",1.2,"MLB Avg (1.2)","HR/9","{:.1f}"), use_container_width=True)
        with c2:
            st.plotly_chart(season_bar("K-BB%","K-BB% by Season (higher=better)",14.5,"MLB Avg 14.5%","K-BB %","{:.1f}"), use_container_width=True)

        sel_s4p = st.selectbox("Season for Statcast Batted Ball", sorted(sel_seasons, reverse=True), key="bb_s")
        st.markdown('<div class="section-header">Monthly Batted Ball from Statcast</div>', unsafe_allow_html=True)
        sc_bb = {}
        for p in PLAYERS:
            mid = mlbam_ids[p]
            if mid:
                with st.spinner(f"Loading Statcast for {p}..."):
                    raw = get_statcast_pitcher_raw(mid, sel_s4p)
                    sc_bb[p] = agg_statcast_pitch_monthly(raw)
            else:
                sc_bb[p] = pd.DataFrame()

        c3,c4 = st.columns(2)
        with c3:
            st.plotly_chart(monthly_line(sc_bb,"EV_avg","Avg Exit Velocity Against by Month",
                88.5,"MLB Avg 88.5","mph",sel_s4p), use_container_width=True)
        with c4:
            st.plotly_chart(monthly_line(sc_bb,"HardHit_pct","Hard Hit % Against by Month",
                37.5,"MLB Avg 37.5%","Hard Hit %",sel_s4p), use_container_width=True)

    # ── TAB 5: ADVANCED ────────────────────────────────────────────────────────
    with t5:
        st.markdown('<div class="section-header">Advanced Pitching Metrics</div>', unsafe_allow_html=True)
        adv_cols = ["Name","Season","ERA","WHIP","K/9","BB/9","K%","BB%","K-BB%","HR/9"]
        avail_adv = [c for c in adv_cols if c in all_fg.columns]
        adv_tbl = pd.concat([p_seasons(p) for p in PLAYERS])[avail_adv].sort_values(["Name","Season"])
        afmt = {c:"{:.2f}" for c in ["ERA","WHIP"]}
        afmt.update({c:"{:.1f}" for c in ["K/9","BB/9","K%","BB%","K-BB%","HR/9"]})
        st.dataframe(adv_tbl.style.format(afmt,na_rep="N/A")
                                  .background_gradient(subset=[c for c in ["ERA","WHIP","HR/9"] if c in adv_tbl.columns], cmap="RdYlGn_r")
                                  .background_gradient(subset=[c for c in ["K%","K-BB%","K/9"] if c in adv_tbl.columns], cmap="RdYlGn"),
                     use_container_width=True, hide_index=True)
        st.info("FIP, xFIP, SIERA, WAR are FanGraphs-only metrics. "
                "Visit fangraphs.com for those advanced indicators.")

        st.markdown('<div class="divider"></div>', unsafe_allow_html=True)
        c1,c2 = st.columns(2)
        with c1:
            st.plotly_chart(season_bar("ERA","ERA by Season (lower=better)",
                4.20,"MLB Avg (4.20)","ERA","{:.2f}"), use_container_width=True)
        with c2:
            st.plotly_chart(season_bar("K/9","K/9 by Season (higher=better)",
                9.0,"MLB Avg (9.0)","K/9","{:.1f}"), use_container_width=True)
        c3,c4 = st.columns(2)
        with c3:
            st.plotly_chart(season_bar("WHIP","WHIP by Season (lower=better)",
                1.28,"MLB Avg (1.28)","WHIP","{:.3f}"), use_container_width=True)
        with c4:
            st.plotly_chart(season_bar("K-BB%","K-BB% by Season (higher=better)",
                14.5,"MLB Avg 14.5%","K-BB %","{:.1f}"), use_container_width=True)

        sel_s5p = st.selectbox("Season for Statcast Velocity Trends", sorted(sel_seasons,reverse=True), key="adv_s")
        sc_adv = {}
        for p in PLAYERS:
            mid = mlbam_ids[p]
            if mid:
                with st.spinner(f"Loading Statcast for {p}..."):
                    raw = get_statcast_pitcher_raw(mid, sel_s5p)
                    sc_adv[p] = agg_statcast_pitch_monthly(raw)
            else:
                sc_adv[p] = pd.DataFrame()

        st.markdown('<div class="section-header">Monthly Velocity & Spin from Statcast</div>', unsafe_allow_html=True)
        c5,c6 = st.columns(2)
        with c5:
            st.plotly_chart(monthly_line(sc_adv,"Velo_avg","Avg Fastball Velocity by Month",
                93.5,"MLB Avg 93.5","mph",sel_s5p), use_container_width=True)
        with c6:
            st.plotly_chart(monthly_line(sc_adv,"SwStr_pct","Swinging Strike % by Month (higher=better)",
                10.8,"MLB Avg 10.8%","SwStr %",sel_s5p), use_container_width=True)

# ── Footer ─────────────────────────────────────────────────────────────────────
st.markdown('<div class="divider"></div>', unsafe_allow_html=True)
st.markdown("""
<div style="text-align:center;color:#9BA3B8;font-size:.78rem;padding:6px 0 14px">
  Data: FanGraphs &nbsp;·&nbsp; Baseball Savant (Statcast) &nbsp;·&nbsp; MLB Stats API
  &nbsp;·&nbsp; pybaseball 2.2.7 &nbsp;&nbsp;|&nbsp;&nbsp;
  Built by Sean Bosworth &nbsp;·&nbsp; June 2026
</div>""", unsafe_allow_html=True)
