"""
MLB Player Comparison Dashboard
Compare any hitter vs. hitter  |  pitcher vs. pitcher
"""
import warnings, os, requests
warnings.filterwarnings("ignore")

import streamlit as st
import streamlit.components.v1 as components
import pandas as pd
import numpy as np
import json, math

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
    initial_sidebar_state="collapsed",
)

# ── Constants ──────────────────────────────────────────────────────────────────
ALL_SEASONS   = [2023, 2024, 2025, 2026]
PA_COL        = "#B0C4DE"   # Player A — light steel silver
PB_COL        = "#2ECC9B"   # Player B — neptune green
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

# ── ECharts CDN renderer ───────────────────────────────────────────────────────
_ECHARTS_CDN = "https://cdn.jsdelivr.net/npm/echarts@5.4.3/dist/echarts.min.js"
_ek = [0]

def _nan_safe(obj):
    if isinstance(obj, float) and math.isnan(obj): return None
    raise TypeError(type(obj))

def ech(opts, height=360):
    _ek[0] += 1
    opts.setdefault("backgroundColor", CARD_BG)
    payload = json.dumps(opts, default=_nan_safe, ensure_ascii=False)
    html = f"""<!DOCTYPE html><html><head>
<script src="{_ECHARTS_CDN}"></script>
<style>html,body{{margin:0;padding:0;background:{CARD_BG}}}</style>
</head><body>
<div id="c{_ek[0]}" style="width:100%;height:{height}px"></div>
<script>
var c=echarts.init(document.getElementById('c{_ek[0]}'));
c.setOption({payload});
new ResizeObserver(function(){{c.resize()}}).observe(document.getElementById('c{_ek[0]}'));
</script></body></html>"""
    components.html(html, height=height + 8)

def hex_rgba(h, a=1.0):
    h = h.lstrip('#')
    r,g,b = int(h[0:2],16), int(h[2:4],16), int(h[4:6],16)
    return f"rgba({r},{g},{b},{a})"

def _grad(color):
    return {"type":"linear","x":0,"y":0,"x2":0,"y2":1,
            "colorStops":[{"offset":0,"color":color},
                          {"offset":1,"color":hex_rgba(color,0.25)}]}

def _hgrad(color):
    return {"type":"linear","x":0,"y":0,"x2":1,"y2":0,
            "colorStops":[{"offset":0,"color":color},
                          {"offset":1,"color":hex_rgba(color,0.35)}]}

def _tt():
    return {"trigger":"axis","axisPointer":{"type":"shadow"},
            "backgroundColor":CARD_BG,"borderColor":LINE_CLR,
            "textStyle":{"color":TEXT,"fontSize":11}}

def _base(title):
    return {
        "backgroundColor": CARD_BG,
        "title": {"text":title,"textStyle":{"color":TEXT,"fontSize":13,"fontWeight":"bold"},
                  "top":4,"left":"center"},
        "tooltip": _tt(),
        "legend": {"bottom":4,"textStyle":{"color":TEXT,"fontSize":11},
                   "data":[]},
    }

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
[data-testid="collapsedControl"]{display:none !important}
[data-testid="stSidebarCollapseButton"]{display:none !important}
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
            if pa < 1: continue
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
            if ip < 0.1: continue
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

_FG_HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

@st.cache_data(ttl=3600, show_spinner=False)
def load_fangraphs_batting(seasons_tuple):
    """WAR, wRC+, wOBA, Dollars, Pull%/Oppo% from FanGraphs API."""
    frames = []
    for season in seasons_tuple:
        url = (f"https://www.fangraphs.com/api/leaders/major-league/data"
               f"?pos=all&stats=bat&lg=all&qual=0&season={season}&season1={season}"
               f"&month=0&hand=&team=0&pageitems=2000000&pagenum=1"
               f"&ind=0&rost=0&players=&type=2&postseason=&sortdir=default&sortstat=WAR")
        try:
            r = requests.get(url, headers=_FG_HEADERS, timeout=20)
            r.raise_for_status()
            for row in r.json().get("data", []):
                mid = row.get("xMLBAMID")
                if not mid: continue
                frames.append({"IDmlb": int(mid), "Season": int(season),
                    "WAR": row.get("WAR"), "wRC+": row.get("wRC+"),
                    "wOBA_fg": row.get("wOBA"), "Dollars": row.get("Dollars"),
                    "Pull%": row.get("Pull%"), "Oppo%": row.get("Oppo%")})
        except Exception:
            pass
    return pd.DataFrame(frames) if frames else pd.DataFrame()

@st.cache_data(ttl=3600, show_spinner=False)
def load_fangraphs_pitching(seasons_tuple):
    """WAR, FIP, xFIP, SIERA, Dollars from FanGraphs API."""
    frames = []
    for season in seasons_tuple:
        url = (f"https://www.fangraphs.com/api/leaders/major-league/data"
               f"?pos=all&stats=pit&lg=all&qual=0&season={season}&season1={season}"
               f"&month=0&hand=&team=0&pageitems=2000000&pagenum=1"
               f"&ind=0&rost=0&players=&type=2&postseason=&sortdir=default&sortstat=WAR")
        try:
            r = requests.get(url, headers=_FG_HEADERS, timeout=20)
            r.raise_for_status()
            for row in r.json().get("data", []):
                mid = row.get("xMLBAMID")
                if not mid: continue
                frames.append({"IDmlb": int(mid), "Season": int(season),
                    "WAR": row.get("WAR"), "FIP": row.get("FIP"),
                    "xFIP": row.get("xFIP"), "SIERA": row.get("SIERA"),
                    "Dollars": row.get("Dollars")})
        except Exception:
            pass
    return pd.DataFrame(frames) if frames else pd.DataFrame()

@st.cache_data(ttl=3600, show_spinner=False)
def get_platoon_splits(mlbam_id, season, group="hitting"):
    """L/R platoon splits from MLB Stats API sitCodes vl (vs LHP) and vr (vs RHP)."""
    url = (f"https://statsapi.mlb.com/api/v1/people/{mlbam_id}/stats"
           f"?stats=statSplits&group={group}&season={season}&gameType=R&sitCodes=vl,vr")
    try:
        r = requests.get(url, headers=MLB_HEADERS, timeout=15)
        splits = r.json().get("stats", [{}])[0].get("splits", [])
        rows = []
        for sp in splits:
            desc = sp.get("split", {}).get("description", "")
            s    = sp.get("stat", {})
            pa   = int(s.get("plateAppearances", 0) or 0)
            ab   = int(s.get("atBats", 1) or 1)
            so   = int(s.get("strikeOuts", 0) or 0)
            bb   = int(s.get("baseOnBalls", 0) or 0)
            hr   = int(s.get("homeRuns", 0) or 0)
            rows.append({"Split": desc, "PA": pa,
                "AVG": float(s.get("avg", 0) or 0),
                "OBP": float(s.get("obp", 0) or 0),
                "SLG": float(s.get("slg", 0) or 0),
                "OPS": float(s.get("ops", 0) or 0),
                "HR": hr,
                "K%":  round(so / max(ab, 1) * 100, 1),
                "BB%": round(bb / max(pa, 1) * 100, 1)})
        return pd.DataFrame(rows)
    except Exception:
        return pd.DataFrame()

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
def get_fielding_stats(mlbam_id, seasons_tuple):
    rows = []
    for season in seasons_tuple:
        url = (f"https://statsapi.mlb.com/api/v1/people/{mlbam_id}/stats"
               f"?stats=season&group=fielding&season={season}&gameType=R&sportId=1")
        try:
            splits = requests.get(url, headers=MLB_HEADERS, timeout=15).json()\
                             .get("stats",[{}])[0].get("splits",[])
        except Exception:
            continue
        for sp in splits:
            s = sp.get("stat", {})
            pos = sp.get("position", {}).get("abbreviation", "")
            ip_raw = str(s.get("innings","0"))
            try: inn = float(ip_raw)
            except: inn = 0
            po = int(s.get("putOuts", 0))
            a  = int(s.get("assists", 0))
            e  = int(s.get("errors", 0))
            if int(s.get("gamesPlayed", 0)) < 1: continue
            if po + a + e == 0: continue   # DH / no fielding chances — skip
            chances = po + a + e
            fp = round((po + a) / chances, 3) if chances > 0 else None
            rows.append({
                "Season": season, "Pos": pos,
                "G":  int(s.get("gamesPlayed", 0)),
                "GS": int(s.get("gamesStarted", 0)),
                "INN": round(inn, 1),
                "PO": po, "A": a, "E": e,
                "Chances": chances,
                "FP": fp,
            })
    return pd.DataFrame(rows)

@st.cache_data(ttl=3600, show_spinner=False)
def get_fa_info(mlbam_id):
    """Debut date, team, position, and estimated CBA status from MLB Stats API.
    serviceTime is not in the public API — we estimate from mlbDebutDate."""
    from datetime import date as _date
    try:
        r = requests.get(
            f"https://statsapi.mlb.com/api/v1/people/{mlbam_id}?hydrate=currentTeam",
            headers=MLB_HEADERS, timeout=10)
        r.raise_for_status()
        people = r.json().get("people", [])
        if not people:
            return {}
        p     = people[0]
        debut = p.get("mlbDebutDate", "")
        team  = p.get("currentTeam", {}).get("name", "Unknown")
        pos   = p.get("primaryPosition", {}).get("abbreviation", "")
        # Estimate MLB years from debut date (calendar years; actual service time
        # may be lower if player had significant IL time)
        svc_float = 0.0
        fa_year   = None
        if debut:
            debut_year = int(debut[:4])
            svc_float  = float(_date.today().year - debut_year)
            fa_year    = debut_year + 6
        if svc_float >= 6.0:
            status, sc = "FA Eligible", "#2ECC9B"
        elif svc_float >= 3.0:
            arb_n = min(3, int(svc_float) - 2)
            status, sc = f"Arb {arb_n} Eligible", "#C4A962"
        elif svc_float >= 2.0:
            status, sc = "Approaching Arb", "#C4A962"
        else:
            status, sc = "Pre-Arbitration", SUBTEXT
        return {"debut": debut, "svc_float": svc_float,
                "team": team, "pos": pos,
                "status": status, "status_clr": sc, "fa_year": fa_year}
    except Exception:
        return {}

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
        EV=("launch_speed","mean"),
    ).reset_index()
    total = agg["Count"].sum()
    agg["Usage%"] = (agg["Count"]/total*100).round(1)
    agg["Velo"]   = agg["Velo"].round(1)
    agg["Spin"]   = agg["Spin"].round(0)
    agg["xwOBA"]  = agg["xwOBA"].round(3)
    agg["EV"]     = agg["EV"].round(1)
    agg["Pitch"]  = agg["pitch_type"].map(PITCH_NAMES).fillna(agg["pitch_type"])
    return agg.sort_values("Usage%", ascending=False)

# ── Controls (top of page, no sidebar needed) ──────────────────────────────────
st.markdown('<div class="section-header">Select Players</div>', unsafe_allow_html=True)
ctrl1, ctrl2, ctrl3 = st.columns([1, 1, 2])
with ctrl1:
    mode = st.radio("Compare", ["Hitters","Pitchers"], horizontal=True)
with ctrl2:
    sel_seasons = st.multiselect("Seasons", ALL_SEASONS, default=[2024,2025,2026])
    if not sel_seasons:
        sel_seasons = [2025]
seasons_key = tuple(sorted(sel_seasons))

all_fg = pd.DataFrame()
load_error = None
with st.spinner("Loading player list..."):
    try:
        all_fg = load_mlb_hitting(seasons_key) if mode=="Hitters" else load_mlb_pitching(seasons_key)
    except Exception as e:
        load_error = str(e)

if all_fg.empty or load_error:
    st.error("Could not load player list.")
    st.code(load_error or "No data returned.", language=None)
    st.stop()

# Merge FanGraphs advanced stats (WAR, wRC+/FIP/xFIP/SIERA, Dollars)
with st.spinner("Loading FanGraphs advanced stats..."):
    try:
        fg_adv = load_fangraphs_batting(seasons_key) if mode == "Hitters" \
                 else load_fangraphs_pitching(seasons_key)
        if not fg_adv.empty:
            all_fg["IDmlb"]    = pd.to_numeric(all_fg["IDmlb"], errors="coerce")
            all_fg["Season"]   = pd.to_numeric(all_fg["Season"], errors="coerce").astype(int)
            fg_adv["IDmlb"]    = pd.to_numeric(fg_adv["IDmlb"], errors="coerce")
            fg_adv["Season"]   = pd.to_numeric(fg_adv["Season"], errors="coerce").astype(int)
            all_fg = all_fg.merge(fg_adv, on=["IDmlb", "Season"], how="left")
    except Exception:
        pass

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

pcol1, pcol2 = st.columns(2)
with pcol1:
    player_a = st.selectbox("Player A", player_list,
                            index=player_list.index(def_a) if def_a in player_list else 0)
with pcol2:
    pb_opts = [p for p in player_list if p != player_a]
    def_b_i = pb_opts.index(def_b) if def_b in pb_opts else 0
    player_b = st.selectbox("Player B", pb_opts, index=def_b_i)

st.markdown("---")

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
    t1,t2,t3,t4,t5,t6 = st.tabs(["Overview","Hitting","Defense","Statcast","Plate Discipline","Free Agent"])
else:
    t1,t2,t3,t4,t5,t6 = st.tabs(["Overview","Results","Arsenal","Batted Ball","Advanced","Free Agent"])

# ════════════════════════════════════════════════════════════════════════════════
# SHARED: performance index bar (used in both Overview tabs)
# ════════════════════════════════════════════════════════════════════════════════
def perf_index_bar(metrics, avgs, title):
    cats = [m[0] for m in metrics]
    series = []
    for i, player in enumerate(PLAYERS):
        items = []
        for label, col, fmt, lower in metrics:
            s = p_seasons(player)
            v = None
            if not s.empty and col in s.columns:
                raw = s[col].iloc[-1]
                if pd.notna(raw): v = float(raw)
            if v is not None and col in avgs and avgs[col]:
                idx = round((avgs[col]/v*100) if lower else (v/avgs[col]*100), 1)
                actual = fmt.format(v)
            else:
                idx = None; actual = "N/A"
            items.append({"value": idx,
                "label": {"show": True, "position": "right",
                          "formatter": actual, "color": TEXT, "fontSize": 10}})
        ser = {
            "name": player, "type": "bar",
            "data": items,
            "itemStyle": {"color": COLORS[player], "borderRadius": [0, 4, 4, 0]},
        }
        if i == 0:
            ser["markLine"] = {
                "silent": True, "symbol": "none",
                "lineStyle": {"color": GOLD, "type": "dashed", "width": 2},
                "data": [{"xAxis": 100}],
                "label": {"show": True, "formatter": "MLB Avg", "color": GOLD, "position": "end"}
            }
        series.append(ser)
    opts = {
        **_base(title),
        "legend": {"bottom": 4, "textStyle": {"color": TEXT}, "data": PLAYERS},
        "grid": {"left": "3%", "right": "16%", "top": "10%", "bottom": "10%", "containLabel": True},
        "xAxis": {"type": "value", "min": 40, "max": 175,
                  "splitLine": {"lineStyle": {"color": LINE_CLR}},
                  "axisLabel": {"color": SUBTEXT},
                  "axisLine": {"lineStyle": {"color": LINE_CLR}}},
        "yAxis": {"type": "category", "data": cats,
                  "axisLabel": {"color": TEXT, "fontSize": 11},
                  "axisLine": {"lineStyle": {"color": LINE_CLR}},
                  "splitLine": {"show": False}},
        "series": series,
    }
    ech(opts, height=max(300, len(metrics) * 58))

def season_bar(col, title, ref_val, ref_label, y_title, fmt="{:.3f}", height=340):
    season_set = sorted({
        str(int(r["Season"]))
        for p in PLAYERS
        for _, r in p_seasons(p).dropna(subset=[col]).iterrows()
    })
    series = []
    for player in PLAYERS:
        s = p_seasons(player).dropna(subset=[col])
        sm = {str(int(r["Season"])): float(r[col]) for _, r in s.iterrows()}
        data = [sm.get(ss) for ss in season_set]
        color = COLORS[player]
        ser = {
            "name": player, "type": "bar", "barMaxWidth": 70,
            "itemStyle": {"color": _grad(color), "borderRadius": [4, 4, 0, 0]},
            "data": [{"value": v,
                      "label": {"show": v is not None, "position": "top",
                                "formatter": fmt.format(v) if v is not None else "",
                                "color": TEXT, "fontSize": 10}}
                     for v in data],
        }
        if not series and ref_val is not None:
            ser["markLine"] = {
                "silent": True, "symbol": "none",
                "lineStyle": {"color": GOLD, "type": "dashed", "width": 1.5},
                "data": [{"yAxis": ref_val}],
                "label": {"show": True, "formatter": ref_label, "color": GOLD,
                          "position": "insideEndTop", "backgroundColor": CARD_BG,
                          "padding": [2, 4]}
            }
        series.append(ser)
    opts = {
        **_base(title),
        "legend": {"bottom": 4, "textStyle": {"color": TEXT}, "data": PLAYERS},
        "grid": {"left": "5%", "right": "8%", "top": "15%", "bottom": "15%", "containLabel": True},
        "xAxis": {"type": "category", "data": season_set,
                  "axisLabel": {"color": TEXT},
                  "axisLine": {"lineStyle": {"color": LINE_CLR}}},
        "yAxis": {"type": "value", "name": y_title,
                  "nameTextStyle": {"color": SUBTEXT},
                  "splitLine": {"lineStyle": {"color": LINE_CLR}},
                  "axisLabel": {"color": SUBTEXT},
                  "axisLine": {"lineStyle": {"color": LINE_CLR}}},
        "series": series,
    }
    ech(opts, height=height)

def monthly_line(monthly_dict, col, title, ref_val, ref_label, y_title, sel_season, height=340):
    all_months = []
    for p in PLAYERS:
        df = monthly_dict.get(p, pd.DataFrame())
        if df.empty or col not in df.columns: continue
        for m in df.sort_values("Month_Num")["Month"].tolist():
            if m not in all_months: all_months.append(m)
    series = []
    for player in PLAYERS:
        df = monthly_dict.get(player, pd.DataFrame())
        if df.empty or col not in df.columns: continue
        s = df.dropna(subset=[col]).sort_values("Month_Num")
        mm = {row["Month"]: row[col] for _, row in s.iterrows()}
        data = [mm.get(m) for m in all_months]
        color = COLORS[player]
        ser = {
            "name": player, "type": "line", "smooth": True,
            "data": data, "symbol": "circle", "symbolSize": 7,
            "lineStyle": {"color": color, "width": 2.5},
            "itemStyle": {"color": color},
            "areaStyle": {"color": {"type": "linear", "x": 0, "y": 0, "x2": 0, "y2": 1,
                "colorStops": [{"offset": 0, "color": hex_rgba(color, 0.35)},
                               {"offset": 1, "color": hex_rgba(color, 0.0)}]}},
        }
        if not series and ref_val is not None:
            ser["markLine"] = {
                "silent": True, "symbol": "none",
                "lineStyle": {"color": GOLD, "type": "dotted", "width": 1.5},
                "data": [{"yAxis": ref_val}],
                "label": {"show": True, "formatter": ref_label, "color": GOLD}
            }
        series.append(ser)
    opts = {
        **_base(title),
        "legend": {"bottom": 4, "textStyle": {"color": TEXT}, "data": PLAYERS},
        "grid": {"left": "5%", "right": "5%", "top": "15%", "bottom": "15%", "containLabel": True},
        "xAxis": {"type": "category", "data": all_months, "boundaryGap": False,
                  "axisLabel": {"color": TEXT},
                  "axisLine": {"lineStyle": {"color": LINE_CLR}}},
        "yAxis": {"type": "value", "name": y_title,
                  "nameTextStyle": {"color": SUBTEXT},
                  "splitLine": {"lineStyle": {"color": LINE_CLR}},
                  "axisLabel": {"color": SUBTEXT}},
        "series": series,
    }
    ech(opts, height=height)

# ════════════════════════════════════════════════════════════════════════════════
# SHARED: GM Summary (auto-narrative, Overview tab)
# ════════════════════════════════════════════════════════════════════════════════
def gm_summary():
    def _val(player, col):
        r = p_latest(player)
        return float(r[col]) if r is not None and col in r.index and pd.notna(r.get(col)) else None

    bullets = []
    if mode == "Hitters":
        # Bullet 1: Offensive value via wRC+
        wrc = {p: _val(p, "wRC+") for p in PLAYERS}
        ops = {p: _val(p, "OPS")  for p in PLAYERS}
        if all(v is not None for v in wrc.values()):
            best = max(wrc, key=lambda x: wrc[x])
            other = [p for p in PLAYERS if p != best][0]
            bullets.append(
                f"**Offensive value:** {best} is the stronger offensive player — wRC+ "
                f"**{wrc[best]:.0f}** vs. {wrc[other]:.0f} for {other} "
                f"(100 = league average; each point above 100 = 1% better than the average hitter).")
        elif all(v is not None for v in ops.values()):
            best = max(ops, key=lambda x: ops[x])
            other = [p for p in PLAYERS if p != best][0]
            bullets.append(
                f"**Offensive value:** {best} leads in OPS ({ops[best]:.3f} vs. {ops[other]:.3f} for {other}).")

        # Bullet 2: Plate discipline
        bb = {p: _val(p, "BB%") for p in PLAYERS}
        k  = {p: _val(p, "K%")  for p in PLAYERS}
        if all(v is not None for v in bb.values()) and all(v is not None for v in k.values()):
            disc = max(bb, key=lambda x: bb[x])
            k_str = " / ".join(f"{p}: {k[p]:.1f}%" for p in PLAYERS)
            bullets.append(
                f"**Plate discipline:** {disc} draws more walks ({bb[disc]:.1f}% BB rate). "
                f"Strikeout rates — {k_str} (MLB avg ~22%).")

        # Bullet 3: WAR / dollar value
        war = {p: _val(p, "WAR")     for p in PLAYERS}
        dol = {p: _val(p, "Dollars") for p in PLAYERS}
        if all(v is not None for v in war.values()):
            best = max(war, key=lambda x: war[x])
            other = [p for p in PLAYERS if p != best][0]
            dol_str = f" (est. market value ~${dol[best]:.1f}M)" if dol.get(best) else ""
            bullets.append(
                f"**Win value:** {best} generated **{war[best]:.1f} fWAR** last season{dol_str}, "
                f"vs. {war[other]:.1f} WAR for {other}. "
                f"A 2-WAR player is a solid regular; 5+ WAR is All-Star caliber.")

    else:  # Pitchers
        # Bullet 1: ERA vs FIP per player
        era = {p: _val(p, "ERA") for p in PLAYERS}
        fip = {p: _val(p, "FIP") for p in PLAYERS}
        for p in PLAYERS:
            if era.get(p) is not None and fip.get(p) is not None:
                gap = fip[p] - era[p]
                verdict = ("ERA outpacing peripherals — positive regression likely" if gap > 0.30
                           else "underperforming peripherals — negative regression likely" if gap < -0.30
                           else "ERA and peripherals in line — results look sustainable")
                bullets.append(
                    f"**{p} — ERA vs. FIP:** {era[p]:.2f} ERA / {fip[p]:.2f} FIP — *{verdict}*.")

        # Bullet 2: Strikeout stuff
        k9 = {p: _val(p, "K/9") for p in PLAYERS}
        if all(v is not None for v in k9.values()):
            best = max(k9, key=lambda x: k9[x])
            other = [p for p in PLAYERS if p != best][0]
            bullets.append(
                f"**Swing-and-miss:** {best} leads in strikeouts at **{k9[best]:.1f} K/9** "
                f"vs. {k9[other]:.1f} for {other} (MLB avg ~9.0).")

        # Bullet 3: WAR
        war = {p: _val(p, "WAR")     for p in PLAYERS}
        dol = {p: _val(p, "Dollars") for p in PLAYERS}
        if all(v is not None for v in war.values()):
            best = max(war, key=lambda x: war[x])
            other = [p for p in PLAYERS if p != best][0]
            dol_str = f" (~${dol[best]:.1f}M market value)" if dol.get(best) else ""
            bullets.append(
                f"**Win value:** {best} was worth **{war[best]:.1f} fWAR**{dol_str} "
                f"vs. {war[other]:.1f} for {other}.")

    if not bullets:
        return
    st.markdown('<div class="section-header">GM Summary</div>', unsafe_allow_html=True)
    st.markdown(
        f'<div class="info-box">' +
        "".join(f"<p style='margin:4px 0'>• {b}</p>" for b in bullets) +
        "</div>", unsafe_allow_html=True)
    st.markdown('<div class="divider"></div>', unsafe_allow_html=True)

# ════════════════════════════════════════════════════════════════════════════════
# TAB 1 — OVERVIEW (both modes)
# ════════════════════════════════════════════════════════════════════════════════
with t1:
    gm_summary()
    if mode == "Hitters":
        hit_metrics = [
            ("AVG",    "AVG",   "{:.3f}", False),
            ("OBP",    "OBP",   "{:.3f}", False),
            ("SLG",    "SLG",   "{:.3f}", False),
            ("OPS",    "OPS",   "{:.3f}", False),
            ("wRC+",   "wRC+",  "{:.0f}", False),
            ("BB %",   "BB%",   "{:.1f}%",False),
            ("K % (lower=better)","K%","{:.1f}%",True),
        ]
        HIT_AVG["wRC+"] = 100
        st.markdown('<div class="section-header">Latest Season Performance Index</div>', unsafe_allow_html=True)
        perf_index_bar(hit_metrics, HIT_AVG,
                       "Latest Season Stats vs. MLB Average — 100 = League Average")
        st.markdown('<div class="divider"></div>', unsafe_allow_html=True)
        ov1, ov2 = st.columns(2)
        with ov1:
            season_bar("WAR","fWAR by Season (FanGraphs)",2.0,"2 WAR = Solid Starter","fWAR","{:.1f}")
        with ov2:
            season_bar("wRC+","wRC+ by Season",100,"MLB Avg (100)","wRC+","{:.0f}")

    else:  # Pitchers
        pit_metrics = [
            ("ERA (lower=better)", "ERA",   "{:.2f}", True),
            ("FIP (lower=better)", "FIP",   "{:.2f}", True),
            ("WHIP (lower=better)","WHIP",  "{:.3f}", True),
            ("K %",   "K%",    "{:.1f}%", False),
            ("BB % (lower=better)","BB%",  "{:.1f}%", True),
            ("K-BB %","K-BB%", "{:.1f}%", False),
            ("K/9",   "K/9",   "{:.1f}",  False),
        ]
        PIT_AVG["FIP"] = 4.20
        st.markdown('<div class="section-header">Latest Season Performance Index</div>', unsafe_allow_html=True)
        perf_index_bar(pit_metrics, PIT_AVG,
                       "Latest Season Pitching Index vs. MLB Average — 100 = League Average")
        st.markdown('<div class="divider"></div>', unsafe_allow_html=True)
        ov1, ov2 = st.columns(2)
        with ov1:
            season_bar("WAR","fWAR by Season (FanGraphs)",2.0,"2 WAR = Solid Starter","fWAR","{:.1f}")
        with ov2:
            season_bar("ERA","ERA by Season",4.20,"MLB Avg (4.20)","ERA","{:.2f}")

    # Scouting grades (if available for selected players)
    has_grades = any(p in SCOUTING for p in PLAYERS)
    if has_grades:
        st.markdown('<div class="divider"></div>', unsafe_allow_html=True)
        st.markdown('<div class="section-header">Scouting Tool Grades — 20-80 Scale (FanGraphs)</div>', unsafe_allow_html=True)
        tools = ["Hit","Power","Speed","Field","Arm"] if mode=="Hitters" else ["FB Velo","Command","Stamina","Deception","Arm Strength"]
        sc_series = []
        for i, player in enumerate(PLAYERS):
            if player not in SCOUTING: continue
            grades = [SCOUTING[player].get(t,50) for t in tools]
            ser = {
                "name": player, "type": "bar",
                "data": [{"value": g, "label": {"show": True, "position": "right",
                    "formatter": f"{g} — {grade_label(g)}", "color": TEXT, "fontSize": 10}}
                    for g in grades],
                "itemStyle": {"color": COLORS[player], "borderRadius": [0,4,4,0]},
            }
            if i == 0:
                ser["markArea"] = {"silent": True, "data": [
                    [{"xAxis":20,"itemStyle":{"color":"rgba(231,76,60,0.08)"}},{"xAxis":40}],
                    [{"xAxis":40,"itemStyle":{"color":"rgba(230,126,34,0.08)"}},{"xAxis":50}],
                    [{"xAxis":50,"itemStyle":{"color":"rgba(196,169,98,0.08)"}},{"xAxis":60}],
                    [{"xAxis":60,"itemStyle":{"color":"rgba(46,204,113,0.08)"}},{"xAxis":80}],
                ]}
                ser["markLine"] = {"silent":True,"symbol":"none",
                    "lineStyle":{"color":GOLD,"type":"dashed","width":1.5},
                    "data":[{"xAxis":50}],"label":{"show":False}}
            sc_series.append(ser)
        ech({
            **_base("Tool Grades — 20-80 Scale"),
            "legend": {"bottom":4,"textStyle":{"color":TEXT},"data":[p for p in PLAYERS if p in SCOUTING]},
            "grid": {"left":"3%","right":"22%","top":"10%","bottom":"10%","containLabel":True},
            "xAxis": {"type":"value","min":20,"max":80,
                      "axisLabel":{"color":SUBTEXT,"formatter":"{value}"},
                      "splitLine":{"lineStyle":{"color":LINE_CLR}},
                      "axisLine":{"lineStyle":{"color":LINE_CLR}},
                      "axisTick":{"show":True}},
            "yAxis": {"type":"category","data":tools,
                      "axisLabel":{"color":TEXT,"fontSize":11},
                      "axisLine":{"lineStyle":{"color":LINE_CLR}}},
            "series": sc_series,
        }, height=320)
        st.markdown("""<div class="info-box">
        <b style="color:#C4A962">20-80 Scale:</b> &nbsp;
        20=Poor &nbsp;·&nbsp; 40=Below Avg &nbsp;·&nbsp; 50=Average &nbsp;·&nbsp;
        55=Above Avg &nbsp;·&nbsp; 60=Plus &nbsp;·&nbsp; 70=Well Above Avg &nbsp;·&nbsp; 80=Elite
        </div>""", unsafe_allow_html=True)

# ════════════════════════════════════════════════════════════════════════════════
# SHARED: Free Agent tab (called from both hitter and pitcher branches)
# ════════════════════════════════════════════════════════════════════════════════
def render_fa_tab():
    st.markdown('<div class="section-header">Free Agent & Contract Status</div>', unsafe_allow_html=True)
    fa_data = {}
    for p in PLAYERS:
        mid = mlbam_ids[p]
        if mid:
            with st.spinner(f"Loading FA info for {p}..."):
                fa_data[p] = get_fa_info(mid)
        else:
            fa_data[p] = {}

    # ── Player cards ──────────────────────────────────────────────────────────
    p_cols = st.columns(len(PLAYERS))
    for col, player in zip(p_cols, PLAYERS):
        d   = fa_data.get(player, {})
        clr = COLORS[player]
        sc  = d.get("status_clr", SUBTEXT)
        with col:
            st.markdown(f'<div class="section-header" style="color:{clr}">{player}</div>',
                        unsafe_allow_html=True)
            if not d:
                st.warning("Could not load FA info from MLB Stats API.")
                continue
            st.markdown(f"""
<div style="background:{CARD_BG};border:1px solid {LINE_CLR};border-radius:8px;padding:16px">
  <div style="font-size:.78rem;color:{SUBTEXT};letter-spacing:.05em">CURRENT TEAM</div>
  <div style="font-size:1rem;color:{TEXT};font-weight:600;margin-bottom:10px">{d.get('team','—')}</div>
  <div style="font-size:.78rem;color:{SUBTEXT};letter-spacing:.05em">POSITION</div>
  <div style="font-size:.95rem;color:{TEXT};margin-bottom:10px">{d.get('pos','—')}</div>
  <div style="font-size:.78rem;color:{SUBTEXT};letter-spacing:.05em">MLB DEBUT</div>
  <div style="font-size:.95rem;color:{TEXT};margin-bottom:10px">{d.get('debut','—')}</div>
  <div style="font-size:.78rem;color:{SUBTEXT};letter-spacing:.05em">YEARS IN MLB (EST.)</div>
  <div style="font-size:.95rem;color:{TEXT};margin-bottom:10px">~{int(d.get('svc_float',0))} seasons</div>
  <div style="font-size:.78rem;color:{SUBTEXT};letter-spacing:.05em">FA ELIGIBILITY (EST.)</div>
  <div style="font-size:.95rem;font-weight:600;color:{sc};margin-bottom:10px">{d.get('status','—')}</div>
  <div style="font-size:.72rem;color:#9BA3B8;margin-top:-6px;margin-bottom:10px">Players under extension may show FA Eligible</div>
  <div style="font-size:.78rem;color:{SUBTEXT};letter-spacing:.05em">EST. FA YEAR</div>
  <div style="font-size:1.05rem;color:{TEXT};font-weight:700">{d.get('fa_year','—')}</div>
</div>""", unsafe_allow_html=True)
            q = player.replace(" ", "+") + "+spotrac+mlb+contract"
            st.link_button("View contract on Spotrac →",
                           f"https://www.google.com/search?q={q}",
                           use_container_width=True)

    # ── Service time progress chart ───────────────────────────────────────────
    st.markdown('<div class="divider"></div>', unsafe_allow_html=True)
    st.markdown('<div class="section-header">Service Time Progress to Free Agency</div>',
                unsafe_allow_html=True)
    valid = [(p, fa_data[p]) for p in PLAYERS if fa_data.get(p) and "svc_float" in fa_data[p]]
    if valid:
        names  = [p for p, _ in valid]
        earned = [round(min(d["svc_float"], 6.0), 3) for _, d in valid]
        remain = [round(max(0.0, 6.0 - d["svc_float"]), 3) for _, d in valid]
        ech({
            "backgroundColor": CARD_BG,
            "title": {"text": "Est. MLB Seasons Since Debut  (6 = typically FA eligible)",
                      "textStyle": {"color": TEXT, "fontSize": 13}, "left": "center", "top": 4},
            "tooltip": {"trigger": "axis", "axisPointer": {"type": "shadow"},
                        "backgroundColor": CARD_BG, "borderColor": LINE_CLR,
                        "textStyle": {"color": TEXT, "fontSize": 11}},
            "legend": {"bottom": 4, "textStyle": {"color": TEXT},
                       "data": ["Service Time", "Remaining to FA"]},
            "grid": {"left": "5%", "right": "5%", "top": "18%", "bottom": "18%",
                     "containLabel": True},
            "xAxis": {"type": "value", "min": 0, "max": 6,
                      "axisLabel": {"color": SUBTEXT, "formatter": "{value} yr"},
                      "splitLine": {"lineStyle": {"color": LINE_CLR}},
                      "axisLine": {"lineStyle": {"color": LINE_CLR}}},
            "yAxis": {"type": "category", "data": names,
                      "axisLabel": {"color": TEXT},
                      "axisLine": {"lineStyle": {"color": LINE_CLR}}},
            "series": [
                {"name": "Service Time", "type": "bar", "stack": "svc", "barMaxWidth": 55,
                 "data": [{"value": v,
                           "itemStyle": {"color": COLORS[p], "borderRadius": [0, 0, 0, 0]}}
                          for p, v in zip(names, earned)],
                 "label": {"show": True, "position": "inside",
                           "formatter": "{c} yrs", "color": "#111",
                           "fontSize": 11, "fontWeight": "bold"}},
                {"name": "Remaining to FA", "type": "bar", "stack": "svc", "barMaxWidth": 55,
                 "data": [{"value": v,
                           "itemStyle": {"color": hex_rgba(LINE_CLR, 0.7),
                                         "borderRadius": [0, 4, 4, 0]}}
                          for v in remain],
                 "label": {"show": False}},
            ],
        }, height=210)

    # ── CBA rules ─────────────────────────────────────────────────────────────
    st.markdown("""<div class="info-box">
    <b style="color:#C4A962">MLB Service Time Rules (2023 CBA):</b><br/>
    <b>Pre-Arb:</b> &lt;3 service years — team controls salary &nbsp;·&nbsp;
    <b>Super Two:</b> Top ~22% of players with 2–3 yrs earn a 4th arbitration year &nbsp;·&nbsp;
    <b>Arb 1–3:</b> 3–6 service years — salary set by arbitration &nbsp;·&nbsp;
    <b>FA Eligible:</b> 6 full service years — earned the right to free agency<br/>
    <i style="color:#9BA3B8">FA Eligibility is estimated from MLB debut date (calendar years, not exact service time).
    Players under a contract extension will show as FA Eligible even if they are not currently a free agent.
    See Spotrac for current contract status and projected next deal.</i>
    </div>""", unsafe_allow_html=True)

    # ── Full contract links ────────────────────────────────────────────────────
    st.markdown('<div class="divider"></div>', unsafe_allow_html=True)
    st.markdown('<div class="section-header">Full Contract & Projected Value</div>',
                unsafe_allow_html=True)
    st.caption("Current salary, multi-year contract breakdown, and projected next contract "
               "are available on Spotrac.")
    lc1, lc2 = st.columns(2)
    for col, player in zip([lc1, lc2], PLAYERS):
        with col:
            q = player.replace(" ", "+") + "+spotrac+mlb+contract"
            st.link_button(f"Spotrac: {player} →",
                           f"https://www.google.com/search?q={q}",
                           use_container_width=True)

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
                monthly_line(monthly_hit,"AVG","AVG by Month",0.248,"MLB Avg (.248)","AVG",sel_s)
            with c2:
                monthly_line(monthly_hit,"OPS","OPS by Month",0.720,"MLB Avg (.720)","OPS",sel_s)
            c3,c4 = st.columns(2)
            with c3:
                monthly_line(monthly_hit,"HR","Home Runs by Month",None,None,"HR",sel_s)
            with c4:
                monthly_line(monthly_hit,"OBP","OBP by Month",0.320,"MLB Avg (.320)","OBP",sel_s)

        st.markdown('<div class="divider"></div>', unsafe_allow_html=True)
        st.markdown('<div class="section-header">Season Totals</div>', unsafe_allow_html=True)
        disp_cols = ["Name","Season","G","PA","AB","H","AVG","OBP","SLG","OPS","wRC+","WAR","HR","RBI","SB","BB","SO","K%","BB%"]
        avail = [c for c in disp_cols if c in all_fg.columns]
        tbl = pd.concat([p_seasons(p) for p in PLAYERS])[avail].sort_values(["Name","Season"])
        fmt_map = {c:"{:.3f}" for c in ["AVG","OBP","SLG","OPS"]}
        fmt_map.update({c:"{:.1f}" for c in ["K%","BB%","WAR"]})
        fmt_map["wRC+"] = "{:.0f}"
        st.dataframe(tbl.style.format(fmt_map, na_rep="N/A")
                              .background_gradient(subset=[c for c in ["AVG","OBP","SLG","OPS","wRC+"] if c in tbl.columns], cmap="RdYlGn")
                              .background_gradient(subset=[c for c in ["WAR"] if c in tbl.columns], cmap="RdYlGn"),
                     use_container_width=True, hide_index=True)

        st.markdown('<div class="divider"></div>', unsafe_allow_html=True)
        h1, h2 = st.columns(2)
        with h1:
            season_bar("wRC+","wRC+ by Season (park-adjusted offense)",100,"MLB Avg (100)","wRC+","{:.0f}")
        with h2:
            season_bar("WAR","fWAR by Season",2.0,"2 WAR = Solid Starter","fWAR","{:.1f}")

        # ── Platoon Splits ──────────────────────────────────────────────────────
        st.markdown('<div class="divider"></div>', unsafe_allow_html=True)
        st.markdown('<div class="section-header">Platoon Splits — vs. LHP / vs. RHP</div>', unsafe_allow_html=True)
        sel_split_s = st.selectbox("Season", sorted(sel_seasons, reverse=True), key="split_hit_s")
        sp_cols = st.columns(len(PLAYERS))
        for col, player in zip(sp_cols, PLAYERS):
            with col:
                mid = mlbam_ids[player]
                clr = COLORS[player]
                st.markdown(f'<div class="section-header" style="color:{clr}">{player}</div>', unsafe_allow_html=True)
                if not mid:
                    st.info("No MLBAM ID.")
                    continue
                with st.spinner(f"Loading splits for {player}..."):
                    sp_df = get_platoon_splits(mid, sel_split_s, "hitting")
                if sp_df.empty:
                    st.info("No split data available.")
                    continue
                st.dataframe(sp_df.style.format(
                    {"AVG":"{:.3f}","OBP":"{:.3f}","SLG":"{:.3f}","OPS":"{:.3f}",
                     "K%":"{:.1f}","BB%":"{:.1f}"}, na_rep="N/A")
                    .background_gradient(subset=["OPS"], cmap="RdYlGn"),
                    use_container_width=True, hide_index=True)
        # Side-by-side OPS split chart
        sp_data = {}
        for player in PLAYERS:
            mid = mlbam_ids[player]
            if mid:
                sp_data[player] = get_platoon_splits(mid, sel_split_s, "hitting")
        split_labels = ["vs. LHP", "vs. RHP"]
        split_series = []
        for player in PLAYERS:
            df = sp_data.get(player, pd.DataFrame())
            ops_vals = []
            for lbl in split_labels:
                row = df[df["Split"].str.contains("Left|Right", case=False)] if not df.empty else pd.DataFrame()
                if not row.empty:
                    match = row[row["Split"].str.contains("Left" if "LHP" in lbl else "Right", case=False)]
                    ops_vals.append(round(float(match["OPS"].iloc[0]), 3) if not match.empty else None)
                else:
                    ops_vals.append(None)
            split_series.append({"name": player, "type": "bar", "barMaxWidth": 60,
                "itemStyle": {"color": _grad(COLORS[player]), "borderRadius": [4,4,0,0]},
                "data": [{"value": v, "label": {"show": v is not None, "position": "top",
                    "formatter": f"{v:.3f}" if v else "", "color": TEXT, "fontSize": 10}}
                    for v in ops_vals]})
        ech({**_base("OPS by Handedness Split"),
            "legend": {"bottom":4,"textStyle":{"color":TEXT},"data":PLAYERS},
            "grid": {"left":"5%","right":"5%","top":"15%","bottom":"15%","containLabel":True},
            "xAxis": {"type":"category","data":split_labels,"axisLabel":{"color":TEXT},"axisLine":{"lineStyle":{"color":LINE_CLR}}},
            "yAxis": {"type":"value","name":"OPS","splitLine":{"lineStyle":{"color":LINE_CLR}},"axisLabel":{"color":SUBTEXT}},
            "series": split_series}, height=300)

    # ── TAB 3: DEFENSE ─────────────────────────────────────────────────────────
    with t3:
        st.markdown('<div class="section-header">Fielding Stats — MLB Stats API</div>', unsafe_allow_html=True)
        def_frames = []
        for p in PLAYERS:
            mid = mlbam_ids[p]
            if not mid: continue
            with st.spinner(f"Loading fielding stats for {p}..."):
                df_f = get_fielding_stats(mid, seasons_key)
            if df_f.empty: continue
            df_f["Name"] = p
            def_frames.append(df_f)
        if def_frames:
            def_tbl = pd.concat(def_frames, ignore_index=True)
            show_cols = ["Name","Season","Pos","G","GS","INN","PO","A","E","FP"]
            avail_def = [c for c in show_cols if c in def_tbl.columns]
            st.dataframe(
                def_tbl[avail_def].sort_values(["Name","Season"])
                    .style.format({"FP":"{:.3f}","INN":"{:.1f}"}, na_rep="N/A")
                    .background_gradient(subset=["FP"] if "FP" in avail_def else [], cmap="RdYlGn")
                    .background_gradient(subset=["E"] if "E" in avail_def else [], cmap="RdYlGn_r"),
                use_container_width=True, hide_index=True)

            st.markdown('<div class="divider"></div>', unsafe_allow_html=True)
            c1, c2 = st.columns(2)

            def _def_bar(df_all, col, title, ref_val, ref_lbl, y_title, fmt):
                season_set = sorted({str(int(r["Season"])) for _,r in df_all.iterrows()})
                series = []
                for player in PLAYERS:
                    sub = df_all[df_all["Name"]==player]
                    if sub.empty: continue
                    if col == "FP":
                        # Weighted FP: (total PO + A) / (total chances) per season
                        agg = (sub.groupby("Season")
                                  .apply(lambda x: round(
                                      (x["PO"].sum() + x["A"].sum()) /
                                      max(x["Chances"].sum(), 1), 3))
                                  .reset_index(name="FP"))
                    else:
                        # Counting stats: sum across all positions per season
                        agg = sub.groupby("Season")[col].sum().reset_index()
                    sm = {str(int(r["Season"])): (float(r[col]) if pd.notna(r[col]) else None)
                          for _,r in agg.iterrows()}
                    data = [sm.get(s) for s in season_set]
                    color = COLORS[player]
                    ser = {"name":player,"type":"bar","barMaxWidth":70,
                           "itemStyle":{"color":_grad(color),"borderRadius":[4,4,0,0]},
                           "data":[{"value":v,"label":{"show":v is not None,"position":"top",
                               "formatter":fmt.format(v) if v else "","color":TEXT,"fontSize":10}}
                               for v in data]}
                    if not series and ref_val:
                        ser["markLine"] = {"silent":True,"symbol":"none",
                            "lineStyle":{"color":GOLD,"type":"dashed","width":1.5},
                            "data":[{"yAxis":ref_val}],
                            "label":{"show":True,"formatter":ref_lbl,"color":GOLD,
                                     "position":"insideEndTop","backgroundColor":CARD_BG,"padding":[2,4]}}
                    series.append(ser)
                ech({**_base(title),
                    "legend":{"bottom":4,"textStyle":{"color":TEXT},"data":PLAYERS},
                    "grid":{"left":"5%","right":"8%","top":"15%","bottom":"15%","containLabel":True},
                    "xAxis":{"type":"category","data":season_set,"axisLabel":{"color":TEXT},"axisLine":{"lineStyle":{"color":LINE_CLR}}},
                    "yAxis":{"type":"value","name":y_title,"nameTextStyle":{"color":SUBTEXT},"splitLine":{"lineStyle":{"color":LINE_CLR}},"axisLabel":{"color":SUBTEXT}},
                    "series":series}, height=320)

            with c1:
                _def_bar(def_tbl, "FP", "Fielding % by Season", 0.985, "MLB Avg (.985)", "FP", "{:.3f}")
            with c2:
                _def_bar(def_tbl, "A", "Outfield Assists by Season", None, None, "Assists", "{:.0f}")
        else:
            st.info("No fielding data available for selected players and seasons.")

        st.markdown('<div class="divider"></div>', unsafe_allow_html=True)
        st.markdown("""<div class="info-box">
        <b style="color:#C4A962">Advanced Defensive Metrics (OAA, UZR, DRS):</b> These require
        Baseball Savant / FanGraphs lookups.
        &nbsp;<a href="https://baseballsavant.mlb.com/leaderboard/outs_above_average" target="_blank"
        style="color:#C4A962">⟶ Baseball Savant OAA Leaderboard</a>
        &nbsp;&nbsp;
        <a href="https://www.fangraphs.com/leaders/major-league?pos=of&stats=fld" target="_blank"
        style="color:#C4A962">⟶ FanGraphs Fielding Leaders</a>
        </div>""", unsafe_allow_html=True)

    # ── TAB 4: STATCAST ────────────────────────────────────────────────────────
    with t4:
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
            monthly_line(sc_monthly,"EV_avg","Avg Exit Velocity by Month",88.5,"MLB Avg 88.5","mph",sel_s3)
        with c2:
            monthly_line(sc_monthly,"xBA","xBA by Month",0.248,"MLB Avg (.248)","xBA",sel_s3)
        c3,c4 = st.columns(2)
        with c3:
            monthly_line(sc_monthly,"HardHit_pct","Hard Hit % by Month",37.5,"MLB Avg 37.5%","Hard Hit %",sel_s3)
        with c4:
            monthly_line(sc_monthly,"xwOBA","xwOBA by Month",0.317,"MLB Avg (.317)","xwOBA",sel_s3)

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
                slbls = sorted({str(r["Season"]) for _,r in sc_career.iterrows()})
                def _career_bar(metric, title, ref, ref_lbl, yname):
                    series = []
                    for p in PLAYERS:
                        sub = sc_career[sc_career["Player"]==p].dropna(subset=[metric])
                        sm = {str(int(r["Season"])): round(r[metric],1) for _,r in sub.iterrows()}
                        data = [sm.get(s) for s in slbls]
                        color = COLORS[p]
                        ser = {"name":p,"type":"bar","barMaxWidth":70,
                               "itemStyle":{"color":_grad(color),"borderRadius":[4,4,0,0]},
                               "data":[{"value":v,"label":{"show":v is not None,"position":"top",
                                   "formatter":str(v) if v else "","color":TEXT,"fontSize":10}}
                                   for v in data]}
                        if not series:
                            ser["markLine"] = {"silent":True,"symbol":"none",
                                "lineStyle":{"color":GOLD,"type":"dashed","width":1.5},
                                "data":[{"yAxis":ref}],
                                "label":{"show":True,"formatter":ref_lbl,"color":GOLD,"position":"end"}}
                        series.append(ser)
                    return {**_base(title),
                        "legend":{"bottom":4,"textStyle":{"color":TEXT},"data":PLAYERS},
                        "grid":{"left":"5%","right":"5%","top":"15%","bottom":"15%","containLabel":True},
                        "xAxis":{"type":"category","data":slbls,"axisLabel":{"color":TEXT},"axisLine":{"lineStyle":{"color":LINE_CLR}}},
                        "yAxis":{"type":"value","name":yname,"nameTextStyle":{"color":SUBTEXT},"splitLine":{"lineStyle":{"color":LINE_CLR}},"axisLabel":{"color":SUBTEXT}},
                        "series":series}
                with c5:
                    ech(_career_bar("EV_avg","Avg Exit Velocity by Season",88.5,"MLB Avg","mph"))
                with c6:
                    ech(_career_bar("HardHit_pct","Hard Hit % by Season",37.5,"MLB Avg","%"))

    # ── TAB 5: PLATE DISCIPLINE ────────────────────────────────────────────────
    with t5:
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
            monthly_line(sc_disc,"Chase_pct","Chase Rate by Month (lower=better)",30.0,"MLB Avg 30%","Chase %",sel_s4)
        with c2:
            monthly_line(sc_disc,"SwStr_pct","Swinging Strike % by Month (lower=better)",10.8,"MLB Avg 10.8%","SwStr %",sel_s4)
        c3,c4 = st.columns(2)
        with c3:
            monthly_line(sc_disc,"ZContact_pct","Zone Contact % by Month (higher=better)",84.0,"MLB Avg 84%","Z-Contact %",sel_s4)
        with c4:
            season_bar("BB%","Walk Rate by Season (%)",8.5,"MLB Avg 8.5%","BB %","{:.1f}")

    # ── TAB 6: FREE AGENT ──────────────────────────────────────────────────────
    with t6:
        render_fa_tab()

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
            monthly_line(monthly_pit,"ERA","ERA by Month",4.20,"MLB Avg (4.20)","ERA",sel_s2)
        with c2:
            monthly_line(monthly_pit,"WHIP","WHIP by Month",1.28,"MLB Avg (1.28)","WHIP",sel_s2)
        c3,c4 = st.columns(2)
        with c3:
            monthly_line(monthly_pit,"K/9","K/9 by Month",9.0,"MLB Avg (9.0)","K/9",sel_s2)
        with c4:
            monthly_line(monthly_pit,"BB/9","BB/9 by Month (lower=better)",3.1,"MLB Avg (3.1)","BB/9",sel_s2)

        st.markdown('<div class="divider"></div>', unsafe_allow_html=True)
        st.markdown('<div class="section-header">Career Season Totals</div>', unsafe_allow_html=True)
        p_cols = ["Name","Season","G","GS","IP","W","L","ERA","FIP","xFIP","SIERA","WHIP","K/9","BB/9","K%","BB%","K-BB%","WAR"]
        avail_p = [c for c in p_cols if c in all_fg.columns]
        p_tbl = pd.concat([p_seasons(p) for p in PLAYERS])[avail_p].sort_values(["Name","Season"])
        pfmt = {c:"{:.2f}" for c in ["ERA","FIP","xFIP","SIERA","WHIP"]}
        pfmt.update({c:"{:.1f}" for c in ["IP","K/9","BB/9","K%","BB%","K-BB%","WAR"]})
        st.dataframe(p_tbl.style.format(pfmt, na_rep="N/A")
                               .background_gradient(subset=[c for c in ["ERA","FIP","xFIP","WHIP"] if c in p_tbl.columns], cmap="RdYlGn_r")
                               .background_gradient(subset=[c for c in ["K%","K-BB%","K/9","WAR"] if c in p_tbl.columns], cmap="RdYlGn"),
                     use_container_width=True, hide_index=True)

        st.markdown('<div class="divider"></div>', unsafe_allow_html=True)
        pr1, pr2 = st.columns(2)
        with pr1:
            season_bar("FIP","FIP vs ERA by Season — FIP shows true skill",4.20,"MLB Avg (4.20)","FIP","{:.2f}")
        with pr2:
            season_bar("xFIP","xFIP by Season (normalizes HR/FB rate)",4.20,"MLB Avg (4.20)","xFIP","{:.2f}")

        # ── Platoon Splits (pitcher) ────────────────────────────────────────────
        st.markdown('<div class="divider"></div>', unsafe_allow_html=True)
        st.markdown('<div class="section-header">Platoon Splits — vs. LHB / vs. RHB</div>', unsafe_allow_html=True)
        sel_pit_split_s = st.selectbox("Season", sorted(sel_seasons, reverse=True), key="split_pit_s")
        pit_sp_cols = st.columns(len(PLAYERS))
        for col, player in zip(pit_sp_cols, PLAYERS):
            with col:
                mid = mlbam_ids[player]
                clr = COLORS[player]
                st.markdown(f'<div class="section-header" style="color:{clr}">{player}</div>', unsafe_allow_html=True)
                if not mid:
                    st.info("No MLBAM ID.")
                    continue
                with st.spinner(f"Loading splits for {player}..."):
                    sp_df = get_platoon_splits(mid, sel_pit_split_s, "pitching")
                if sp_df.empty:
                    st.info("No split data available.")
                    continue
                st.dataframe(sp_df.style.format(
                    {"AVG":"{:.3f}","OBP":"{:.3f}","SLG":"{:.3f}","OPS":"{:.3f}",
                     "K%":"{:.1f}","BB%":"{:.1f}"}, na_rep="N/A")
                    .background_gradient(subset=["OPS"], cmap="RdYlGn_r"),
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
                palette = [color,"#4A5568","#718096","#A0AEC0","#CBD5E0","#E2E8F0"][:len(ars)]
                ech({
                    "backgroundColor": CARD_BG,
                    "title": {"text":"Pitch Usage %","textStyle":{"color":TEXT,"fontSize":13},"left":"center","top":4},
                    "tooltip": {"trigger":"item","backgroundColor":CARD_BG,"borderColor":LINE_CLR,"textStyle":{"color":TEXT}},
                    "series": [{"type":"pie","radius":["35%","65%"],"center":["50%","55%"],
                        "data":[{"value":row["Usage%"],"name":row["Pitch"]} for _,row in ars.iterrows()],
                        "label":{"color":TEXT,"fontSize":11},
                        "itemStyle":{"borderRadius":4,"borderColor":CARD_BG,"borderWidth":2},
                        "emphasis":{"itemStyle":{"shadowBlur":10,"shadowColor":"rgba(0,0,0,0.5)"}}}],
                    "color": palette,
                }, height=300)

            with ca2:
                pitches = ars["Pitch"].tolist()
                evs = [float(v) if pd.notna(v) else None for v in ars["EV"].tolist()]
                ech({
                    "backgroundColor": CARD_BG,
                    "title": {"text":"Avg Exit Velocity by Pitch (mph)","textStyle":{"color":TEXT,"fontSize":13},"left":"center","top":4},
                    "tooltip": {"trigger":"axis","backgroundColor":CARD_BG,"borderColor":LINE_CLR,"textStyle":{"color":TEXT}},
                    "grid": {"left":"3%","right":"18%","top":"15%","bottom":"10%","containLabel":True},
                    "xAxis": {"type":"value","min":75,"max":100,
                              "splitLine":{"lineStyle":{"color":LINE_CLR}},
                              "axisLabel":{"color":SUBTEXT},"axisLine":{"lineStyle":{"color":LINE_CLR}}},
                    "yAxis": {"type":"category","data":pitches,
                              "axisLabel":{"color":TEXT},"axisLine":{"lineStyle":{"color":LINE_CLR}}},
                    "series": [{"type":"bar",
                        "itemStyle":{"color":_hgrad(color),"borderRadius":[0,4,4,0]},
                        "data":[{"value":v,"label":{"show":v is not None,"position":"right",
                            "formatter":f"{v:.1f}" if v is not None else "","color":TEXT,"fontSize":10}}
                            for v in evs]}],
                }, height=300)

            # Arsenal table
            disp_ars = ars[["Pitch","Usage%","Velo","EV","Spin","xwOBA"]].rename(
                columns={"Usage%":"Usage %","Velo":"Release Velo","EV":"Avg EV (mph)","Spin":"Avg Spin (rpm)"})
            st.dataframe(
                disp_ars.style.format({"Usage %":"{:.1f}","Release Velo":"{:.1f}",
                                       "Avg EV (mph)":"{:.1f}","Avg Spin (rpm)":"{:.0f}","xwOBA":"{:.3f}"}, na_rep="N/A")
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
            season_bar("HR/9","HR/9 by Season",1.2,"MLB Avg (1.2)","HR/9","{:.1f}")
        with c2:
            season_bar("K-BB%","K-BB% by Season (higher=better)",14.5,"MLB Avg 14.5%","K-BB %","{:.1f}")

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
            monthly_line(sc_bb,"EV_avg","Avg Exit Velocity Against by Month",88.5,"MLB Avg 88.5","mph",sel_s4p)
        with c4:
            monthly_line(sc_bb,"HardHit_pct","Hard Hit % Against by Month",37.5,"MLB Avg 37.5%","Hard Hit %",sel_s4p)

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
            season_bar("ERA","ERA by Season (lower=better)",4.20,"MLB Avg (4.20)","ERA","{:.2f}")
        with c2:
            season_bar("K/9","K/9 by Season (higher=better)",9.0,"MLB Avg (9.0)","K/9","{:.1f}")
        c3,c4 = st.columns(2)
        with c3:
            season_bar("WHIP","WHIP by Season (lower=better)",1.28,"MLB Avg (1.28)","WHIP","{:.3f}")
        with c4:
            season_bar("K-BB%","K-BB% by Season (higher=better)",14.5,"MLB Avg 14.5%","K-BB %","{:.1f}")

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
            monthly_line(sc_adv,"Velo_avg","Avg Fastball Velocity by Month",93.5,"MLB Avg 93.5","mph",sel_s5p)
        with c6:
            monthly_line(sc_adv,"SwStr_pct","Swinging Strike % by Month (higher=better)",10.8,"MLB Avg 10.8%","SwStr %",sel_s5p)

    # ── TAB 6: FREE AGENT ──────────────────────────────────────────────────────
    with t6:
        render_fa_tab()

# ── Footer ─────────────────────────────────────────────────────────────────────
st.markdown('<div class="divider"></div>', unsafe_allow_html=True)
st.markdown("""
<div style="text-align:center;color:#9BA3B8;font-size:.78rem;padding:6px 0 14px">
  Data: FanGraphs &nbsp;·&nbsp; Baseball Savant (Statcast) &nbsp;·&nbsp; MLB Stats API
  &nbsp;·&nbsp; pybaseball 2.2.7 &nbsp;&nbsp;|&nbsp;&nbsp;
  Built by Sean Bosworth &nbsp;·&nbsp; June 2026
</div>""", unsafe_allow_html=True)
