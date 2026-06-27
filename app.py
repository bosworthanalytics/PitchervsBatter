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

try:
    import anthropic as _anthropic
    _ANT_KEY = st.secrets.get("ANTHROPIC_API_KEY", "")
    HAS_ANTHROPIC = bool(_ANT_KEY and not _ANT_KEY.startswith("paste"))
except Exception:
    HAS_ANTHROPIC = False
    _ANT_KEY = ""

# ── Page ───────────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="MLB Player Comparison | Analytics",
    page_icon="baseball",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Constants ──────────────────────────────────────────────────────────────────
ALL_SEASONS   = [2023, 2024, 2025, 2026]
PA_COL        = "#B0C4DE"   # Player A — light steel silver
PB_COL        = "#00BFFF"   # Player B — electric blue
GOLD          = "#C4A962"   # Chart reference lines — gold
CARD_BG       = "#0F1E32"   # Dark navy card
LINE_CLR      = "#1A2E47"   # Navy border
TEXT          = "#F4F8FF"
SUBTEXT       = "#8B9EC4"
RED_ACCENT    = "#C8102E"   # UI accent — MLB red

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
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;800;900&display=swap');

*{font-family:'Inter',sans-serif}
.stApp{background-color:#07111F}
[data-testid="stSidebar"]{background-color:#0F1E32;border-right:1px solid #1A2E47}

/* Player cards */
.player-card{background:#0F1E32;border-radius:14px;padding:20px;text-align:center;
             border-top:4px solid;margin-bottom:14px;
             box-shadow:0 4px 20px rgba(0,0,0,0.4)}
.player-name{font-size:1.3rem;font-weight:800;color:#F4F8FF;margin:8px 0 2px;letter-spacing:.5px}
.player-team{font-size:.85rem;color:#8B9EC4;font-weight:500}

/* Section headers — Hoopology left-border style */
.section-header{font-size:.82rem;font-weight:800;color:#F4F8FF;text-transform:uppercase;
                letter-spacing:2px;border-left:3px solid #C8102E;
                padding-left:10px;margin:18px 0 12px;line-height:1.4}
.divider{border-top:1px solid #1A2E47;margin:16px 0}
.info-box{padding:10px 14px;background:#0F1E32;border-radius:8px;
          border-left:3px solid #C8102E;font-size:.8rem;color:#8B9EC4;margin-top:6px}

/* Tool cards (feature overview cards) */
.tool-card{background:#0F1E32;border:1px solid #1A2E47;border-radius:12px;
           padding:18px;margin:6px 0;transition:border-color .2s,box-shadow .2s}
.tool-card:hover{border-color:#C8102E;box-shadow:0 2px 16px rgba(200,16,46,0.15)}
.tool-card-title{font-size:.95rem;font-weight:800;color:#F4F8FF;text-transform:uppercase;
                 letter-spacing:1px;margin-bottom:6px}
.tool-card-desc{font-size:.8rem;color:#8B9EC4;line-height:1.5}

/* Stat badge pills */
.stat-badge{display:inline-flex;align-items:center;background:#0F1E32;
            border:1px solid #1A2E47;border-radius:20px;padding:4px 14px;
            font-size:.78rem;color:#8B9EC4;margin:3px}
.stat-badge strong{color:#C8102E;margin-right:4px}

/* Hide Streamlit chrome (keep sidebar toggle visible) */
#MainMenu,footer,header{visibility:hidden}

@media (max-width:768px){
  [data-testid="stDataFrame"] iframe{-webkit-font-smoothing:antialiased;image-rendering:-webkit-optimize-contrast}
  [data-testid="stDataFrame"]>div{-webkit-overflow-scrolling:touch}
}

/* Grade pills */
.grade-pill{display:inline-block;padding:3px 10px;border-radius:12px;
            font-weight:700;font-size:.85rem;color:#fff;margin:2px 0}
.grade-row{display:flex;align-items:center;gap:12px;padding:7px 10px;
           border-bottom:1px solid #1A2E47}
.grade-tool{color:#F4F8FF;font-weight:700;min-width:130px;font-size:.88rem}
.grade-note{color:#8B9EC4;font-size:.78rem;flex:1}

/* Chat bubbles */
.chat-msg-user{background:#0F1E32;border-radius:12px 12px 4px 12px;
               padding:10px 14px;margin:6px 0;color:#F4F8FF;font-size:.9rem;
               border:1px solid #1A2E47}
.chat-msg-bot{background:#112040;border-radius:12px 12px 12px 4px;
              padding:10px 14px;margin:6px 0;color:#F4F8FF;font-size:.9rem;
              border-left:3px solid #C8102E}

/* Nav banner */
.nav-banner{background:linear-gradient(135deg,#0F1E32 0%,#091525 100%);
            border-bottom:2px solid #C8102E;padding:14px 22px;margin-bottom:20px;
            border-radius:10px;display:flex;align-items:center;gap:16px;
            box-shadow:0 4px 24px rgba(0,0,0,0.5)}
.nav-title{color:#F4F8FF;font-size:1.15rem;font-weight:900;letter-spacing:2px;
           text-transform:uppercase}
.nav-title .red{color:#C8102E}
.nav-title .blue{color:#5B9BD5}

/* Streamlit tab styling — active tab uses electric blue */
[data-baseweb="tab-list"]{background:#0F1E32 !important;border-radius:8px;padding:4px;
                           border-bottom:2px solid #1A2E47 !important}
[data-baseweb="tab"]{color:#8B9EC4 !important;font-weight:600 !important;font-size:.82rem !important}
[aria-selected="true"]{color:#00BFFF !important;border-bottom:2px solid #00BFFF !important}

/* Sidebar nav styling */
[data-testid="stSidebar"]{background-color:#0A1525 !important;border-right:1px solid #1A2E47;min-width:220px}
[data-testid="stSidebar"] .sidebar-brand{color:#F4F8FF;font-size:1.05rem;font-weight:900;
  letter-spacing:2px;text-transform:uppercase;padding:6px 0 14px;line-height:1.3}
[data-testid="stSidebar"] .sidebar-brand .red{color:#C8102E}
[data-testid="stSidebar"] .sidebar-brand .blue{color:#00BFFF}
[data-testid="stSidebar"] .sidebar-divider{border-top:1px solid #1A2E47;margin:8px 0 14px}
/* Radio nav items */
[data-testid="stSidebar"] [data-testid="stRadio"] > div{gap:4px}
[data-testid="stSidebar"] [data-testid="stRadio"] label{
  padding:10px 14px;border-radius:8px;color:#8B9EC4;
  font-weight:600;font-size:.88rem;transition:background .15s,color .15s;
  border:1px solid transparent}
[data-testid="stSidebar"] [data-testid="stRadio"] label:hover{
  background:#1A2E47;color:#F4F8FF;border-color:#1A2E47}
[data-testid="stSidebar"] [data-testid="stRadio"] label[data-checked="true"],
[data-testid="stSidebar"] [data-testid="stRadio"] input:checked ~ div{
  background:#0F2540;color:#00BFFF !important;border-color:#00BFFF}

/* Streamlit metric overrides */
[data-testid="stMetric"]{background:#0F1E32;border-radius:10px;padding:12px 16px;
                          border:1px solid #1A2E47}
[data-testid="stMetricLabel"]{color:#8B9EC4 !important;font-size:.78rem !important;
                               text-transform:uppercase;letter-spacing:1px}
[data-testid="stMetricValue"]{color:#F4F8FF !important;font-size:1.5rem !important;font-weight:800 !important}
[data-testid="stMetricDelta"]{font-size:.78rem !important}

/* Button overrides */
.stButton>button{background:#C8102E;color:#fff;border:none;border-radius:8px;
                 font-weight:700;letter-spacing:.5px;transition:background .2s}
.stButton>button:hover{background:#A00D25}

/* Selectbox / radio */
[data-baseweb="select"] div{background:#0F1E32 !important;border-color:#1A2E47 !important;color:#F4F8FF !important}
</style>""", unsafe_allow_html=True)

# ── Particle animation background ─────────────────────────────────────────────
components.html("""
<script>
(function(){
  try {
    var doc = window.parent.document;
    var win = window.parent;
    var old = doc.getElementById('mlb-bg-particles');
    if(old) old.remove();

    var canvas = doc.createElement('canvas');
    canvas.id = 'mlb-bg-particles';
    canvas.style.cssText = 'position:fixed;top:0;left:0;width:100vw;height:100vh;z-index:0;pointer-events:none;opacity:0.55;';
    doc.body.appendChild(canvas);

    var ctx = canvas.getContext('2d');
    var W, H;
    function resize(){ W = win.innerWidth; H = win.innerHeight; canvas.width=W; canvas.height=H; }
    resize();
    win.addEventListener('resize', resize);

    var mouse = {x: W/2, y: H/2};
    doc.addEventListener('mousemove', function(e){ mouse.x=e.clientX; mouse.y=e.clientY; });

    var COLS = [
      [200,16,46],   // MLB red
      [91,155,213],  // MLB blue
      [244,248,255]  // white
    ];

    var N = 75;
    var pts = [];
    for(var i=0;i<N;i++){
      var c = COLS[Math.floor(Math.random()*COLS.length)];
      pts.push({
        x: Math.random()*W, y: Math.random()*H,
        r: Math.random()*1.8+0.4,
        vx:(Math.random()-.5)*0.25, vy:(Math.random()-.5)*0.25,
        cr:c[0], cg:c[1], cb:c[2],
        a: Math.random()*0.45+0.1
      });
    }

    function draw(){
      ctx.clearRect(0,0,W,H);
      for(var i=0;i<pts.length;i++){
        var p=pts[i];
        var dx=mouse.x-p.x, dy=mouse.y-p.y;
        var d=Math.sqrt(dx*dx+dy*dy);
        if(d<180 && d>0){ p.vx-=dx/d*0.018; p.vy-=dy/d*0.018; }
        p.vx*=0.99; p.vy*=0.99;
        p.x+=p.vx; p.y+=p.vy;
        if(p.x<0)p.x=W; if(p.x>W)p.x=0;
        if(p.y<0)p.y=H; if(p.y>H)p.y=0;

        ctx.beginPath();
        ctx.arc(p.x,p.y,p.r,0,Math.PI*2);
        ctx.fillStyle='rgba('+p.cr+','+p.cg+','+p.cb+','+p.a+')';
        ctx.fill();
      }
      for(var i=0;i<pts.length;i++){
        for(var j=i+1;j<pts.length;j++){
          var dx=pts[i].x-pts[j].x, dy=pts[i].y-pts[j].y;
          var d=Math.sqrt(dx*dx+dy*dy);
          if(d<90){
            ctx.beginPath();
            ctx.moveTo(pts[i].x,pts[i].y);
            ctx.lineTo(pts[j].x,pts[j].y);
            ctx.strokeStyle='rgba(26,46,71,'+(1-d/90)*0.4+')';
            ctx.lineWidth=0.6;
            ctx.stroke();
          }
        }
      }
      requestAnimationFrame(draw);
    }
    draw();
  } catch(e){}
})();
</script>
""", height=0)

# ── Cached data loaders ────────────────────────────────────────────────────────

MLB_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; MLBDashboard/1.0)"}

@st.cache_data(ttl=3600, show_spinner=False)
def load_mlb_hitting(seasons_tuple):
    """Season hitting stats for all players via MLB Stats API (never blocked)."""
    frames = []
    for season in seasons_tuple:
        url = (f"https://statsapi.mlb.com/api/v1/stats"
               f"?stats=season&group=hitting&gameType=R&season={season}"
               f"&sportId=1&limit=5000&playerPool=All")
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
               f"&sportId=1&limit=5000&playerPool=All")
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
def load_team_stats(season, group="hitting"):
    url = (f"https://statsapi.mlb.com/api/v1/teams/stats"
           f"?stats=season&group={group}&season={season}&sportIds=1&gameType=R")
    try:
        splits = requests.get(url, headers=MLB_HEADERS, timeout=20).json()\
                         .get("stats", [{}])[0].get("splits", [])
        rows = []
        for sp in splits:
            t = sp.get("team", {}); s = sp.get("stat", {})
            row = {"team_id": t.get("id"), "Team": t.get("name", "")}
            row.update({k: v for k, v in s.items()})
            rows.append(row)
        return pd.DataFrame(rows)
    except Exception:
        return pd.DataFrame()

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
            status, sc = "FA Eligible", "#00BFFF"
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

# ── App Navigation ─────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown(
        '<div class="sidebar-brand">⚾ <span class="red">BOSWORTH</span><br>'
        '<span class="blue">ANALYTICS</span></div>'
        '<div class="sidebar-divider"></div>',
        unsafe_allow_html=True,
    )
    app_mode = st.radio(
        "Navigation",
        ["⚾  Player Comparison", "📊  Team Comparison", "🤖  AI Chat"],
        key="top_app_mode",
        label_visibility="collapsed",
    )
    st.markdown('<div class="sidebar-divider"></div>', unsafe_allow_html=True)
    st.markdown(
        '<div style="color:#8B9EC4;font-size:.72rem;text-transform:uppercase;'
        'letter-spacing:1.5px;padding:4px 0">MLB Analytics Dashboard</div>',
        unsafe_allow_html=True,
    )
# Normalize mode name (strip emoji prefix)
app_mode = app_mode.split("  ", 1)[-1]

st.markdown(
    '<div class="nav-banner">'
    '<span class="nav-title">⚾ <span class="red">BOSWORTH</span> '
    '<span class="blue">ANALYTICS</span> · MLB DASHBOARD</span>'
    '</div>',
    unsafe_allow_html=True,
)

# ════════════════════════════════════════════════════════════════════════════════
# TEAM COMPARISON MODE
# ════════════════════════════════════════════════════════════════════════════════
if app_mode == "Team Comparison":
    st.markdown('<div class="section-header">Team Comparison</div>', unsafe_allow_html=True)
    tc1, tc2, tc3 = st.columns([1, 1, 1])
    with tc1:
        tc_season = st.selectbox("Season", [2026, 2025, 2024, 2023], key="tc_season")
    with tc2:
        tc_group = st.radio("Stats", ["Hitting", "Pitching"], horizontal=True, key="tc_group")

    with st.spinner("Loading team stats..."):
        team_df = load_team_stats(tc_season, tc_group.lower())

    if team_df.empty:
        st.error("Could not load team stats.")
        st.stop()

    team_list = sorted(team_df["Team"].tolist())
    col_a, col_b = st.columns(2)
    with col_a:
        team_a = st.selectbox("Team A", team_list,
                              index=team_list.index("New York Yankees") if "New York Yankees" in team_list else 0,
                              key="tc_team_a")
    with col_b:
        team_b = st.selectbox("Team B", [t for t in team_list if t != team_a],
                              index=0, key="tc_team_b")

    row_a = team_df[team_df["Team"] == team_a].iloc[0]
    row_b = team_df[team_df["Team"] == team_b].iloc[0]

    if tc_group == "Hitting":
        metrics = [("AVG","Batting Avg","{:.3f}",False),("obp","OBP","{:.3f}",False),
                   ("slg","SLG","{:.3f}",False),("ops","OPS","{:.3f}",False),
                   ("homeRuns","HR","{:.0f}",False),("runs","Runs","{:.0f}",False),
                   ("stolenBases","SB","{:.0f}",False),("strikeOuts","K","{:.0f}",True),
                   ("baseOnBalls","BB","{:.0f}",False)]
    else:
        metrics = [("era","ERA","{:.2f}",True),("whip","WHIP","{:.3f}",True),
                   ("strikeOuts","K","{:.0f}",False),("baseOnBalls","BB","{:.0f}",True),
                   ("saves","SV","{:.0f}",False),("inningsPitched","IP","{:.1f}",False),
                   ("homeRuns","HR Allowed","{:.0f}",True)]

    st.markdown('<div class="divider"></div>', unsafe_allow_html=True)
    mc1, mc2 = st.columns(2)
    for i, (col, label, fmt, lower_better) in enumerate(metrics):
        val_a = row_a.get(col, row_a.get(col.lower()))
        val_b = row_b.get(col, row_b.get(col.lower()))
        try:
            va, vb = float(val_a), float(val_b)
            if lower_better:
                color_a = "#2ecc71" if va < vb else ("#e74c3c" if va > vb else "#9BA3B8")
                color_b = "#2ecc71" if vb < va else ("#e74c3c" if vb > va else "#9BA3B8")
            else:
                color_a = "#2ecc71" if va > vb else ("#e74c3c" if va < vb else "#9BA3B8")
                color_b = "#2ecc71" if vb > va else ("#e74c3c" if vb < va else "#9BA3B8")
            str_a, str_b = fmt.format(va), fmt.format(vb)
        except Exception:
            str_a = str_b = "N/A"
            color_a = color_b = "#9BA3B8"

        target = mc1 if i % 2 == 0 else mc2
        with target:
            opts = {
                **_base(label),
                "xAxis": {"type": "category", "data": [team_a, team_b],
                          "axisLabel": {"color": TEXT, "fontSize": 9}},
                "yAxis": {"type": "value", "axisLabel": {"color": SUBTEXT, "fontSize": 9},
                          "splitLine": {"lineStyle": {"color": LINE_CLR}}},
                "series": [{"type": "bar", "barMaxWidth": 60,
                            "data": [
                                {"value": float(val_a) if val_a else 0,
                                 "itemStyle": {"color": color_a},
                                 "label": {"show": True, "position": "top",
                                           "formatter": str_a, "color": TEXT, "fontSize": 10}},
                                {"value": float(val_b) if val_b else 0,
                                 "itemStyle": {"color": color_b},
                                 "label": {"show": True, "position": "top",
                                           "formatter": str_b, "color": TEXT, "fontSize": 10}},
                            ]}],
                "grid": {"left":"8%","right":"8%","top":"22%","bottom":"18%","containLabel":True},
            }
            ech(opts, height=220)

    st.markdown('<div class="divider"></div>', unsafe_allow_html=True)
    show_cols = ["Team"] + [m[0] for m in metrics]
    avail = [c for c in show_cols if c in team_df.columns]
    st.dataframe(team_df[avail].set_index("Team").loc[[team_a, team_b]],
                 use_container_width=True)
    st.stop()

# ════════════════════════════════════════════════════════════════════════════════
# AI CHAT MODE
# ════════════════════════════════════════════════════════════════════════════════
if app_mode == "AI Chat":
    st.markdown('<div class="section-header">AI Baseball Analyst</div>', unsafe_allow_html=True)
    if not HAS_ANTHROPIC:
        st.warning("Add your Anthropic API key to `.streamlit/secrets.toml` to enable the chatbot.")
        st.code('ANTHROPIC_API_KEY = "sk-ant-..."', language="toml")
        st.stop()

    chat_mode = st.radio("Compare", ["Hitters", "Pitchers"], horizontal=True, key="chat_mode")
    chat_season = st.selectbox("Season", [2026, 2025, 2024, 2023], key="chat_season")
    chat_key = tuple(sorted([chat_season]))

    with st.spinner("Loading player list..."):
        chat_fg = load_mlb_hitting(chat_key) if chat_mode == "Hitters" else load_mlb_pitching(chat_key)
        try:
            chat_adv = load_fangraphs_batting(chat_key) if chat_mode == "Hitters" \
                       else load_fangraphs_pitching(chat_key)
            if not chat_adv.empty:
                chat_fg["IDmlb"] = pd.to_numeric(chat_fg["IDmlb"], errors="coerce")
                chat_adv["IDmlb"] = pd.to_numeric(chat_adv["IDmlb"], errors="coerce")
                chat_fg = chat_fg.merge(chat_adv, on=["IDmlb","Season"], how="left")
        except Exception:
            pass

    chat_players = sorted(chat_fg["Name"].dropna().unique().tolist()) if not chat_fg.empty else []
    cp1, cp2 = st.columns(2)
    with cp1:
        chat_pa = st.selectbox("Player A", chat_players, key="chat_pa")
    with cp2:
        chat_pb = st.selectbox("Player B", [p for p in chat_players if p != chat_pa],
                               key="chat_pb")

    def _get_stats_str(name):
        rows = chat_fg[chat_fg["Name"] == name].sort_values("Season", ascending=False)
        if rows.empty: return "No data"
        r = rows.iloc[0]
        keep = (["Season","AVG","OBP","SLG","OPS","wRC+","WAR","HR","RBI","SB","BB%","K%"]
                if chat_mode == "Hitters"
                else ["Season","ERA","WHIP","K/9","BB/9","K%","BB%","WAR","FIP","xFIP"])
        parts = [f"{c}={r[c]:.3f}" if isinstance(r.get(c), float) else f"{c}={r.get(c,'N/A')}"
                 for c in keep if c in r.index]
        return ", ".join(parts)

    sys_prompt = f"""You are an expert MLB analytics assistant for Bosworth Analytics.
You have access to real {chat_season} stats for any player the user asks about.
Mode: {chat_mode}. Answer questions analytically, concisely, and back every claim with numbers.
Do not make up stats — if data is unavailable, say so.

Current comparison players loaded:
{chat_pa}: {_get_stats_str(chat_pa)}
{chat_pb}: {_get_stats_str(chat_pb)}

MLB Averages ({chat_season}): {HIT_AVG if chat_mode == 'Hitters' else PIT_AVG}

You can also discuss any other MLB players in general based on your training knowledge."""

    if "chat_history" not in st.session_state:
        st.session_state.chat_history = []

    for msg in st.session_state.chat_history:
        with st.chat_message(msg["role"],
                             avatar="🧑" if msg["role"] == "user" else "⚾"):
            st.markdown(msg["content"])

    def _find_mentioned_players(msg):
        """Return stats string for any player names detected in the message."""
        msg_lower = msg.lower()
        found = []
        already = {chat_pa.lower(), chat_pb.lower()}
        for name in chat_fg["Name"].dropna().unique():
            if name.lower() in already:
                continue
            parts = [p for p in name.lower().split() if len(p) > 3]
            if any(p in msg_lower for p in parts):
                rows = chat_fg[chat_fg["Name"] == name].sort_values("Season", ascending=False)
                if not rows.empty:
                    found.append(f"{name}: {_get_stats_str(name)}")
        return found

    if prompt := st.chat_input(f"Ask about any MLB player..."):
        st.session_state.chat_history.append({"role": "user", "content": prompt})
        with st.chat_message("user", avatar="🧑"):
            st.markdown(prompt)

        with st.chat_message("assistant", avatar="⚾"):
            with st.spinner("Analyzing..."):
                try:
                    extra = _find_mentioned_players(prompt)
                    dynamic_sys = sys_prompt
                    if extra:
                        dynamic_sys += "\n\nAdditional players mentioned in this query:\n" + "\n".join(extra)
                    client = _anthropic.Anthropic(api_key=_ANT_KEY)
                    resp = client.messages.create(
                        model="claude-haiku-4-5-20251001",
                        max_tokens=700,
                        system=dynamic_sys,
                        messages=[{"role": m["role"], "content": m["content"]}
                                  for m in st.session_state.chat_history],
                    )
                    answer = resp.content[0].text
                except Exception as e:
                    answer = f"Error connecting to AI: {e}"
                st.markdown(answer)
                st.session_state.chat_history.append({"role": "assistant", "content": answer})

    if st.session_state.chat_history:
        if st.button("Clear Chat", key="clear_chat"):
            st.session_state.chat_history = []
            st.rerun()
    st.stop()

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

if mode == "Hitters":
    def_a = next((p for p in player_list if "Judge" in p and "Aaron" in p), player_list[0])
    def_b = next((p for p in player_list if "Harper" in p and "Bryce" in p), player_list[1])
else:
    def_a = next((p for p in player_list if "Schlittler" in p), player_list[0])
    def_b = next((p for p in player_list if "Ohtani" in p), player_list[1])

pcol1, pcol2 = st.columns(2)
with pcol1:
    player_a = st.selectbox("Player A", player_list,
                            index=player_list.index(def_a) if def_a in player_list else 0,
                            key=f"player_a_{mode}")
with pcol2:
    pb_opts = [p for p in player_list if p != player_a]
    def_b_i = pb_opts.index(def_b) if def_b in pb_opts else 0
    player_b = st.selectbox("Player B", pb_opts, index=def_b_i,
                            key=f"player_b_{mode}")

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
    t1,t2,t3,t4,t5,t6,t7 = st.tabs(["Overview","Hitting","Defense","Statcast","Plate Discipline","Free Agent","Scouting Report"])
else:
    t1,t2,t3,t4,t5,t6,t7 = st.tabs(["Overview","Results","Arsenal","Batted Ball","Advanced","Free Agent","Scouting Report"])

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
            if v is not None and col in avgs and avgs[col] and (not lower or v != 0):
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

def season_bar(col, title, ref_val, ref_label, y_title, fmt="{:.3f}", height=340, round_to=None):
    season_set = sorted({
        str(int(r["Season"]))
        for p in PLAYERS
        for _, r in p_seasons(p).dropna(subset=[col]).iterrows()
    })
    series = []
    for player in PLAYERS:
        s = p_seasons(player).dropna(subset=[col])
        sm = {str(int(r["Season"])): (round(float(r[col]), round_to) if round_to is not None else float(r[col])) for _, r in s.iterrows()}
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
                          "position": "insideStartTop", "backgroundColor": CARD_BG,
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
                "label": {"show": True, "formatter": ref_label, "color": GOLD,
                          "position": "insideStartTop", "backgroundColor": CARD_BG,
                          "padding": [2, 4]}
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
def _gm_bullets():
    """Return GM summary bullet strings for the current comparison."""
    def _val(player, col):
        r = p_latest(player)
        return float(r[col]) if r is not None and col in r.index and pd.notna(r.get(col)) else None

    bullets = []
    if mode == "Hitters":
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

        bb = {p: _val(p, "BB%") for p in PLAYERS}
        k  = {p: _val(p, "K%")  for p in PLAYERS}
        if all(v is not None for v in bb.values()) and all(v is not None for v in k.values()):
            disc = max(bb, key=lambda x: bb[x])
            k_str = " / ".join(f"{p}: {k[p]:.1f}%" for p in PLAYERS)
            bullets.append(
                f"**Plate discipline:** {disc} draws more walks ({bb[disc]:.1f}% BB rate). "
                f"Strikeout rates — {k_str} (MLB avg ~22%).")

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

    else:
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

        k9 = {p: _val(p, "K/9") for p in PLAYERS}
        if all(v is not None for v in k9.values()):
            best = max(k9, key=lambda x: k9[x])
            other = [p for p in PLAYERS if p != best][0]
            bullets.append(
                f"**Swing-and-miss:** {best} leads in strikeouts at **{k9[best]:.1f} K/9** "
                f"vs. {k9[other]:.1f} for {other} (MLB avg ~9.0).")

        war = {p: _val(p, "WAR")     for p in PLAYERS}
        dol = {p: _val(p, "Dollars") for p in PLAYERS}
        if all(v is not None for v in war.values()):
            best = max(war, key=lambda x: war[x])
            other = [p for p in PLAYERS if p != best][0]
            dol_str = f" (~${dol[best]:.1f}M market value)" if dol.get(best) else ""
            bullets.append(
                f"**Win value:** {best} was worth **{war[best]:.1f} fWAR**{dol_str} "
                f"vs. {war[other]:.1f} for {other}.")

    return bullets


def gm_summary():
    bullets = _gm_bullets()
    if not bullets:
        return
    st.markdown('<div class="section-header">GM Summary</div>', unsafe_allow_html=True)
    st.markdown(
        f'<div class="info-box">' +
        "".join(f"<p style='margin:4px 0'>• {b}</p>" for b in bullets) +
        "</div>", unsafe_allow_html=True)
    st.markdown('<div class="divider"></div>', unsafe_allow_html=True)


def generate_pdf():
    """Build a formatted PDF comparison report and return bytes."""
    import io, re
    from datetime import date as _dt
    try:
        from fpdf import FPDF
    except ImportError:
        return None

    def _s(v):
        return (str(v)
                .replace("—", "-")   # em dash
                .replace("–", "-")   # en dash
                .replace("•", "*")   # bullet
                .encode("latin-1", "replace").decode("latin-1"))

    def _strip_md(t):
        return re.sub(r"\*+([^*]+)\*+", r"\1", str(t))

    C_HDR  = (14,  17,  23)
    C_SECT = (26,  29,  46)
    C_GOLD = (200, 16, 46)   # MLB red accent for PDF headers
    C_WHT  = (250, 250, 250)
    C_TXT  = (30,  30,  30)
    C_SUB  = (110, 120, 140)
    C_ALT  = (243, 246, 252)
    C_PA   = (70,  120, 195)
    C_PB   = (0,   155, 220)
    C_LINE = (210, 215, 228)

    class _PDF(FPDF):
        def footer(self):
            self.set_y(-13)
            self.set_font("Helvetica", "I", 7)
            self.set_text_color(*C_SUB)
            self.cell(0, 5, _s(
                "MLB Stats API  |  FanGraphs  |  Baseball Savant  "
                "|  MLB Player Comparison Dashboard"), align="C")

    pdf = _PDF(orientation="P", unit="mm", format="A4")
    pdf.set_margins(15, 15, 15)
    pdf.set_auto_page_break(auto=True, margin=20)
    pdf.add_page()

    PW  = pdf.w - 30
    COL = PW / 3

    # Header bar
    import os
    _here = os.path.dirname(os.path.abspath(__file__))
    logo_path = os.path.join(_here, "assets", "Logo.PNG")
    pdf.set_fill_color(*C_HDR)
    pdf.rect(0, 0, pdf.w, 50, "F")
    if os.path.exists(logo_path):
        pdf.image(logo_path, x=5, y=5, h=40)
    pdf.set_y(8)
    pdf.set_font("Helvetica", "B", 19)
    pdf.set_text_color(*C_GOLD)
    pdf.cell(0, 11, "MLB Player Comparison Report", align="C", ln=True)
    pdf.set_font("Helvetica", "B", 13)
    pdf.set_text_color(*C_WHT)
    pdf.cell(0, 9, _s(f"{player_a}  vs.  {player_b}"), align="C", ln=True)
    pdf.set_font("Helvetica", "", 8.5)
    pdf.set_text_color(155, 163, 184)
    pdf.cell(0, 7, _s(
        f"{mode}  |  Seasons: {', '.join(str(s) for s in sorted(sel_seasons))}"
        f"  |  {_dt.today().strftime('%B %d, %Y')}"), align="C", ln=True)
    pdf.set_y(56)

    def sec(title):
        pdf.ln(2)
        pdf.set_fill_color(*C_SECT)
        pdf.set_font("Helvetica", "B", 8.5)
        pdf.set_text_color(*C_GOLD)
        pdf.cell(0, 6.5, _s(f"  {title}"), fill=True, border=0, ln=True)
        pdf.ln(0.5)

    def tbl_hdr():
        pdf.set_fill_color(*C_HDR)
        pdf.set_font("Helvetica", "B", 8.5)
        pdf.set_text_color(*C_WHT)
        pdf.cell(COL, 6.5, "  Metric", fill=True, border=0)
        pdf.set_text_color(*C_PA)
        pdf.cell(COL, 6.5, _s(player_a), align="C", fill=True, border=0)
        pdf.set_text_color(*C_PB)
        pdf.cell(COL, 6.5, _s(player_b), align="C", fill=True, border=0, ln=True)
        pdf.set_draw_color(*C_LINE)
        pdf.cell(PW, 0.2, "", border="T", ln=True)

    _alt = [False]
    def row(label, va, vb, fmt="{}"):
        _alt[0] = not _alt[0]
        pdf.set_fill_color(*(C_ALT if _alt[0] else (255, 255, 255)))
        pdf.set_draw_color(*C_LINE)
        pdf.set_font("Helvetica", "", 8.5)
        def fv(v):
            if v is None: return "-"
            if isinstance(v, str): return _s(v)
            try: return fmt.format(v)
            except: return str(v)
        pdf.set_text_color(*C_TXT)
        pdf.cell(COL, 6.2, _s(f"  {label}"), fill=True, border="B")
        pdf.set_text_color(*C_PA)
        pdf.cell(COL, 6.2, fv(va), align="C", fill=True, border="B")
        pdf.set_text_color(*C_PB)
        pdf.cell(COL, 6.2, fv(vb), align="C", fill=True, border="B", ln=True)
        pdf.set_text_color(*C_TXT)

    ra = p_latest(player_a)
    rb = p_latest(player_b)

    def gv(r, col):
        if r is None or col not in r.index: return None
        v = r.get(col)
        return None if (v is None or (isinstance(v, float) and pd.isna(v))) else v

    sa = gv(ra, "Season"); sb = gv(rb, "Season")
    sy = f"{int(sa) if sa else '-'} / {int(sb) if sb else '-'}"

    if mode == "Hitters":
        sec(f"STANDARD HITTING  -  MOST RECENT SEASON ({sy})")
        tbl_hdr()
        row("Games", gv(ra,"G"),   gv(rb,"G"),   "{:.0f}")
        row("PA",    gv(ra,"PA"),  gv(rb,"PA"),  "{:.0f}")
        row("AVG",   gv(ra,"AVG"), gv(rb,"AVG"), "{:.3f}")
        row("OBP",   gv(ra,"OBP"), gv(rb,"OBP"), "{:.3f}")
        row("SLG",   gv(ra,"SLG"), gv(rb,"SLG"), "{:.3f}")
        row("OPS",   gv(ra,"OPS"), gv(rb,"OPS"), "{:.3f}")
        row("HR",    gv(ra,"HR"),  gv(rb,"HR"),  "{:.0f}")
        row("RBI",   gv(ra,"RBI"), gv(rb,"RBI"), "{:.0f}")
        row("SB",    gv(ra,"SB"),  gv(rb,"SB"),  "{:.0f}")
        row("K%",    gv(ra,"K%"),  gv(rb,"K%"),  "{:.1f}%")
        row("BB%",   gv(ra,"BB%"), gv(rb,"BB%"), "{:.1f}%")
        if any(gv(r, "WAR") is not None for r in [ra, rb]):
            sec("ADVANCED STATS (FANGRAPHS)")
            tbl_hdr()
            row("WAR",   gv(ra,"WAR"),     gv(rb,"WAR"),     "{:.1f}")
            row("wRC+",  gv(ra,"wRC+"),    gv(rb,"wRC+"),    "{:.0f}")
            row("wOBA",  gv(ra,"wOBA_fg"), gv(rb,"wOBA_fg"), "{:.3f}")
            da = gv(ra,"Dollars"); db = gv(rb,"Dollars")
            if da is not None or db is not None:
                row("Est. Value",
                    f"${da:.1f}M" if da is not None else None,
                    f"${db:.1f}M" if db is not None else None)
    else:
        sec(f"STANDARD PITCHING  -  MOST RECENT SEASON ({sy})")
        tbl_hdr()
        row("Games", gv(ra,"G"),    gv(rb,"G"),    "{:.0f}")
        row("GS",    gv(ra,"GS"),   gv(rb,"GS"),   "{:.0f}")
        row("IP",    gv(ra,"IP"),   gv(rb,"IP"),   "{:.1f}")
        wla = (f"{int(gv(ra,'W') or 0)}-{int(gv(ra,'L') or 0)}" if ra is not None else None)
        wlb = (f"{int(gv(rb,'W') or 0)}-{int(gv(rb,'L') or 0)}" if rb is not None else None)
        row("W-L",   wla,           wlb)
        row("ERA",   gv(ra,"ERA"),  gv(rb,"ERA"),  "{:.2f}")
        row("WHIP",  gv(ra,"WHIP"), gv(rb,"WHIP"), "{:.3f}")
        row("K/9",   gv(ra,"K/9"),  gv(rb,"K/9"),  "{:.1f}")
        row("BB/9",  gv(ra,"BB/9"), gv(rb,"BB/9"), "{:.1f}")
        row("K%",    gv(ra,"K%"),   gv(rb,"K%"),   "{:.1f}%")
        row("BB%",   gv(ra,"BB%"),  gv(rb,"BB%"),  "{:.1f}%")
        row("HR/9",  gv(ra,"HR/9"), gv(rb,"HR/9"), "{:.1f}")
        if any(gv(r, "WAR") is not None for r in [ra, rb]):
            sec("ADVANCED STATS (FANGRAPHS)")
            tbl_hdr()
            row("WAR",   gv(ra,"WAR"),   gv(rb,"WAR"),   "{:.1f}")
            row("FIP",   gv(ra,"FIP"),   gv(rb,"FIP"),   "{:.2f}")
            row("xFIP",  gv(ra,"xFIP"),  gv(rb,"xFIP"),  "{:.2f}")
            row("SIERA", gv(ra,"SIERA"), gv(rb,"SIERA"), "{:.2f}")
            da = gv(ra,"Dollars"); db = gv(rb,"Dollars")
            if da is not None or db is not None:
                row("Est. Value",
                    f"${da:.1f}M" if da is not None else None,
                    f"${db:.1f}M" if db is not None else None)

    # GM Summary bullets
    bullets = _gm_bullets()
    if bullets:
        sec("GM SUMMARY")
        pdf.set_font("Helvetica", "", 8.5)
        pdf.set_text_color(*C_TXT)
        for b in bullets:
            pdf.ln(1)
            pdf.multi_cell(PW, 5.5, _s(f"  - {_strip_md(b)}"))

    # Disclaimer
    pdf.ln(4)
    pdf.set_font("Helvetica", "I", 7.5)
    pdf.set_text_color(*C_SUB)
    pdf.multi_cell(0, 4.5, _s(
        "Standard stats from MLB Stats API. Advanced stats (WAR, wRC+, FIP, xFIP, SIERA, Est. Value) "
        "from FanGraphs for most recent selected season. "
        "Service time estimated from MLB debut date."))

    buf = io.BytesIO()
    pdf.output(buf)
    return buf.getvalue()


def _compute_scouting_grades(player):
    """Estimate 20-80 tool grades from available stats for any player."""
    row = p_latest(player)
    if row is None:
        return None

    def gv(col, default=0.0):
        v = row.get(col)
        return float(v) if v is not None and pd.notna(v) else default

    def clamp(x):
        return max(20, min(80, round(x)))

    if mode == "Hitters":
        wrc = gv("wRC+", 100)
        slg = gv("SLG",  0.400)
        avg = gv("AVG",  0.248)
        sb  = gv("SB",   0)
        g   = gv("G",    100)
        iso = slg - avg
        sbr = sb / max(g, 1) * 162
        return {
            "Hit":   clamp(50 + (wrc - 100) * 0.30),
            "Power": clamp(20 + iso * 200),
            "Speed": clamp(35 + sbr * 0.65),
            "Field": 50,
            "Arm":   50,
        }
    else:
        bb  = gv("BB%", 8.5)
        k   = gv("K%",  23.0)
        k9  = gv("K/9", 9.0)
        ip  = gv("IP",  50.0)
        gs  = gv("GS",  0)
        g   = gv("G",   20)
        ipg = ip / max(g, 1)
        is_starter = gs > 0
        stamina = clamp(ipg * 11) if is_starter else clamp(35 + ipg * 5)

        # FB Velo grade from Statcast release_speed (MLB avg ~93.5 mph = 50)
        velo_grade = 50
        if HAS_PB:
            mid = p_mlbam(player)
            if mid:
                for s in sorted(sel_seasons, reverse=True):
                    raw = get_statcast_pitcher_raw(mid, s)
                    if not raw.empty and "release_speed" in raw.columns:
                        fb = raw[raw["pitch_type"].isin(["FF", "SI"])]["release_speed"].dropna()
                        if len(fb) < 5:
                            fb = raw[raw["pitch_type"].isin(["FF", "SI", "FC"])]["release_speed"].dropna()
                        if len(fb) >= 5:
                            velo_grade = clamp(50 + (fb.mean() - 93.5) * 5)
                            break

        return {
            "FB Velo":      velo_grade,
            "Command":      clamp(50 + (8.5 - bb) * 2.5),
            "Stamina":      stamina,
            "Deception":    clamp(50 + (k  - 23.0) * 1.5),
            "Arm Strength": clamp(50 + (k9 - 9.0)  * 3.0),
        }


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
            season_bar("WAR","fWAR by Season (FanGraphs)",2.0,"2 WAR = Solid Starter","fWAR","{:.1f}",round_to=1)
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
            season_bar("WAR","fWAR by Season (FanGraphs)",2.0,"2 WAR = Solid Starter","fWAR","{:.1f}",round_to=1)
        with ov2:
            season_bar("ERA","ERA by Season",4.20,"MLB Avg (4.20)","ERA","{:.2f}")

    # Scouting grades — computed from stats for any player
    sc_grades = {p: _compute_scouting_grades(p) for p in PLAYERS}
    has_grades = any(g is not None for g in sc_grades.values())
    if has_grades:
        st.markdown('<div class="divider"></div>', unsafe_allow_html=True)
        st.markdown('<div class="section-header">Estimated Tool Grades — 20-80 Scale</div>', unsafe_allow_html=True)
        tools = ["Hit","Power","Speed","Field","Arm"] if mode=="Hitters" else ["FB Velo","Command","Stamina","Deception","Arm Strength"]
        sc_series = []
        for i, player in enumerate(PLAYERS):
            grade_data = sc_grades.get(player)
            if grade_data is None: continue
            grades = [grade_data.get(t, 50) for t in tools]
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
            **_base("Estimated Tool Grades — 20-80 Scale"),
            "legend": {"bottom":4,"textStyle":{"color":TEXT},"data":PLAYERS},
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
        <br/><i style="color:#9BA3B8">Grades estimated from available stats (wRC+, ISO, SB, K%, BB%, K/9).
        Field/Arm and FB Velo default to 50 where not derivable from the public API.</i>
        </div>""", unsafe_allow_html=True)

    # ── PDF Export ──────────────────────────────────────────────────────────────
    st.markdown('<div class="divider"></div>', unsafe_allow_html=True)
    st.markdown('<div class="section-header">Export Report</div>', unsafe_allow_html=True)
    _, btn_col = st.columns([3, 1])
    with btn_col:
        try:
            pdf_bytes = generate_pdf()
            if pdf_bytes:
                fname = (f"{player_a.replace(' ','_')}_vs_"
                         f"{player_b.replace(' ','_')}_{max(sel_seasons)}.pdf")
                st.download_button(
                    "Download PDF Report",
                    data=pdf_bytes,
                    file_name=fname,
                    mime="application/pdf",
                    use_container_width=True,
                )
        except Exception as _e:
            st.caption(f"PDF export unavailable: {_e}")

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
            season_bar("WAR","fWAR by Season",2.0,"2 WAR = Solid Starter","fWAR","{:.1f}",round_to=1)

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
                                     "position":"insideStartTop","backgroundColor":CARD_BG,"padding":[2,4]}}
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
                                "label":{"show":True,"formatter":ref_lbl,"color":GOLD,
                                         "position":"insideStartTop","backgroundColor":CARD_BG,"padding":[2,4]}}
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
                    "xAxis": {"type":"value","min":65,"max":90,
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

    # ── TAB 7: SCOUTING REPORT ─────────────────────────────────────────────────
    with t7:
        st.markdown('<div class="section-header">Scouting Report — 20-80 Tool Grades</div>',
                    unsafe_allow_html=True)

        def _grade_color(g):
            if g >= 70: return "#1a7a4a"
            if g >= 60: return "#2ecc71"
            if g >= 55: return "#7dce82"
            if g >= 50: return "#95a5a6"
            if g >= 45: return "#e67e22"
            if g >= 40: return "#e74c3c"
            return "#922b21"

        def _render_grades(player):
            grades = _compute_scouting_grades(player)
            if grades is None:
                st.info(f"Not enough data to compute grades for {player}.")
                return
            st.markdown(f"**{player}**")
            for tool, val in grades.items():
                gc = _grade_color(val)
                gl = grade_label(val)
                st.markdown(
                    f'<div class="grade-row">'
                    f'<span class="grade-tool">{tool}</span>'
                    f'<span class="grade-pill" style="background:{gc};">{val}</span>'
                    f'<span style="color:{gc};font-weight:700;font-size:.8rem;min-width:90px;">{gl}</span>'
                    f'</div>',
                    unsafe_allow_html=True)
            ofp = round(sum(grades.values()) / len(grades))
            gc_ofp = _grade_color(ofp)
            st.markdown(
                f'<div style="margin-top:10px;padding:10px;background:#1A1D2E;border-radius:8px;text-align:center;">'
                f'<span style="color:#9BA3B8;font-size:.75rem;letter-spacing:1px;">OVERALL FUTURE POTENTIAL</span><br/>'
                f'<span style="color:{gc_ofp};font-size:2rem;font-weight:900;">{ofp}</span>'
                f'<span style="color:{gc_ofp};font-size:.9rem;font-weight:700;margin-left:8px;">{grade_label(ofp)}</span>'
                f'</div>', unsafe_allow_html=True)

        sc1, sc2 = st.columns(2)
        with sc1:
            _render_grades(player_a)
        with sc2:
            _render_grades(player_b)

        st.markdown('<div class="divider"></div>', unsafe_allow_html=True)
        st.markdown('<div class="section-header">Tool Grade Radar</div>', unsafe_allow_html=True)

        sc_grades_t7 = {p: _compute_scouting_grades(p) for p in PLAYERS}
        if any(g is not None for g in sc_grades_t7.values()):
            tools_t7 = list(next(g for g in sc_grades_t7.values() if g is not None).keys())
            radar_ind = [{"name": t, "max": 80, "min": 20} for t in tools_t7]
            radar_series = []
            for player in PLAYERS:
                grade_data = sc_grades_t7.get(player)
                if grade_data is None: continue
                radar_series.append({
                    "name": player, "type": "radar",
                    "data": [{"value": [grade_data.get(t, 50) for t in tools_t7],
                              "name": player,
                              "lineStyle": {"color": COLORS[player], "width": 2},
                              "areaStyle": {"color": COLORS[player], "opacity": 0.15},
                              "itemStyle": {"color": COLORS[player]}}]
                })
            ech({
                **_base("20-80 Tool Grades Comparison"),
                "legend": {"bottom": 4, "textStyle": {"color": TEXT}, "data": PLAYERS},
                "radar": {"indicator": radar_ind, "shape": "polygon",
                          "splitLine": {"lineStyle": {"color": LINE_CLR}},
                          "splitArea": {"areaStyle": {"color": [CARD_BG, "#1E2235"]}},
                          "axisName": {"color": TEXT, "fontSize": 11}},
                "series": radar_series,
            }, height=380)

        if mode == "Pitchers":
            st.markdown('<div class="divider"></div>', unsafe_allow_html=True)
            st.markdown('<div class="section-header">Pitch Arsenal from Statcast</div>',
                        unsafe_allow_html=True)
            sc_sel = st.selectbox("Season", sorted(sel_seasons, reverse=True), key="sc_t7")
            for player in PLAYERS:
                mid = p_mlbam(player)
                if not mid: continue
                with st.spinner(f"Loading arsenal for {player}..."):
                    raw = get_statcast_pitcher_raw(mid, sc_sel)
                arsenal = build_arsenal(raw) if not raw.empty else pd.DataFrame()
                if arsenal.empty:
                    st.info(f"No Statcast data for {player} in {sc_sel}.")
                    continue
                st.markdown(f"**{player} — {sc_sel} Arsenal**")
                disp_cols = [c for c in ["pitch_name","count","Velo","AvgVelo","MaxVelo",
                                         "SwStr_pct","InZone_pct","GB_pct"] if c in arsenal.columns]
                st.dataframe(arsenal[disp_cols].style.format(
                    {c: "{:.1f}" for c in disp_cols if c not in ["pitch_name","count"]}
                ), use_container_width=True, hide_index=True)

        st.markdown('<div class="divider"></div>', unsafe_allow_html=True)
        st.markdown('<div class="section-header">GM Summary & Gameplan Notes</div>',
                    unsafe_allow_html=True)
        for bullet in _gm_bullets():
            clean = bullet.replace("**", "")
            st.markdown(f"- {clean}")

# ── Footer ─────────────────────────────────────────────────────────────────────
st.markdown('<div class="divider"></div>', unsafe_allow_html=True)
st.markdown("""
<div style="text-align:center;color:#9BA3B8;font-size:.78rem;padding:6px 0 14px">
  Data: FanGraphs &nbsp;·&nbsp; Baseball Savant (Statcast) &nbsp;·&nbsp; MLB Stats API
  &nbsp;·&nbsp; pybaseball 2.2.7 &nbsp;&nbsp;|&nbsp;&nbsp;
  Built by Sean Bosworth &nbsp;·&nbsp; June 2026
</div>""", unsafe_allow_html=True)
