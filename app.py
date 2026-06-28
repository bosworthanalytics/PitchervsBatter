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
    initial_sidebar_state="collapsed",
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

/* ── Content tab bar — active tab electric blue ── */
[data-baseweb="tab-list"]{background:#0F1E32 !important;border-radius:8px 8px 0 0;
                           padding:4px 4px 0;border-bottom:2px solid #1A2E47 !important}
[data-baseweb="tab"]{color:#8B9EC4 !important;font-weight:600 !important;
                     font-size:.82rem !important;padding:8px 16px !important}
[aria-selected="true"]{color:#00BFFF !important;border-bottom:2px solid #00BFFF !important}

/* ── Top nav radio — scoped ONLY to the nav radio via :has() ── */
[data-testid="stRadio"]:has(input[value="Player Comparison"]) > div {
  display:flex;gap:6px;background:#0A1525;padding:6px;
  border-radius:10px;border:1px solid #1A2E47;margin-bottom:16px}
/* Nav labels only */
[data-testid="stRadio"]:has(input[value="Player Comparison"]) label {
  flex:1;text-align:center;padding:10px 14px;border-radius:8px;
  font-weight:700;font-size:.85rem;color:#8B9EC4;cursor:pointer;
  white-space:nowrap;transition:background .15s,color .15s;border:1px solid transparent}
[data-testid="stRadio"]:has(input[value="Player Comparison"]) label:hover {
  background:#1A2E47;color:#F4F8FF}
[data-testid="stRadio"]:has(input[value="Player Comparison"]) label:has(input:checked) {
  background:#C8102E;color:#fff !important;border-color:#C8102E}
/* Hide radio dots — nav only */
[data-testid="stRadio"]:has(input[value="Player Comparison"]) label > div:first-child {
  display:none !important}

/* ── Multiselect ── */
[data-baseweb="select"] > div{background:#0F1E32 !important;border-color:#1A2E47 !important;padding-left:10px !important}

/* ── Sidebar hidden ── */
[data-testid="stSidebar"]{display:none}
[data-testid="collapsedControl"]{display:none !important}
[data-testid="stSidebarCollapseButton"]{display:none !important}

/* ── Metrics ── */
[data-testid="stMetric"]{background:#0F1E32;border-radius:10px;padding:12px 16px;
                          border:1px solid #1A2E47}
[data-testid="stMetricLabel"]{color:#8B9EC4 !important;font-size:.78rem !important;
                               text-transform:uppercase;letter-spacing:1px}
[data-testid="stMetricValue"]{color:#F4F8FF !important;font-size:1.5rem !important;
                               font-weight:800 !important}
[data-testid="stMetricDelta"]{font-size:.78rem !important}

/* ── All buttons default ── */
.stButton>button{background:#C8102E;color:#fff;border:none;border-radius:8px;
                 font-weight:700;letter-spacing:.5px;transition:background .2s}
.stButton>button:hover{background:#A00D25}

/* ── Selectbox inputs ── */
[data-baseweb="select"] div{background:#0F1E32 !important;border-color:#1A2E47 !important;
                             color:#F4F8FF !important}
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
def load_mlb_fielding(seasons_tuple):
    """Season fielding stats (errors, assists, putouts, DP, fielding%) via MLB Stats API."""
    frames = []
    for season in seasons_tuple:
        url = (f"https://statsapi.mlb.com/api/v1/stats"
               f"?stats=season&group=fielding&gameType=R&season={season}"
               f"&sportId=1&limit=5000&playerPool=All")
        try:
            splits = requests.get(url, headers=MLB_HEADERS, timeout=20).json()\
                             .get("stats",[{}])[0].get("splits",[])
        except Exception as e:
            raise RuntimeError(f"MLB Stats API failed for {season}: {e}")
        rows = []
        for sp in splits:
            p = sp.get("player", {}); t = sp.get("team", {}); s = sp.get("stat", {})
            pos = (sp.get("position") or {}).get("abbreviation", "")
            try: inn = float(s.get("innings", "0") or 0)
            except Exception: inn = 0.0
            rows.append({
                "Name": p.get("fullName",""), "IDmlb": p.get("id"),
                "Team": t.get("name",""), "Season": season, "Pos": pos,
                "E": int(s.get("errors",0)), "A": int(s.get("assists",0)),
                "PO": int(s.get("putOuts",0)), "DP": int(s.get("doublePlays",0)),
                "Chances": int(s.get("chances",0)), "Inn": inn,
                "FPCT": float(s.get("fielding","0") or 0),
            })
        if rows:
            frames.append(pd.DataFrame(rows))
    if not frames:
        raise RuntimeError("MLB Stats API returned no fielding data.")
    return pd.concat(frames, ignore_index=True)

@st.cache_data(ttl=3600, show_spinner=False)
def load_fangraphs_fielding(seasons_tuple):
    """Advanced defense (DRS, UZR, UZR/150, OAA, Def runs) from FanGraphs API."""
    frames = []
    for season in seasons_tuple:
        url = (f"https://www.fangraphs.com/api/leaders/major-league/data"
               f"?pos=all&stats=fld&lg=all&qual=0&season={season}&season1={season}"
               f"&month=0&hand=&team=0&pageitems=2000000&pagenum=1"
               f"&ind=0&rost=0&players=&type=1&postseason=&sortdir=default&sortstat=Def")
        try:
            r = requests.get(url, headers=_FG_HEADERS, timeout=25)
            r.raise_for_status()
            for row in r.json().get("data", []):
                mid = row.get("xMLBAMID")
                if not mid: continue
                frames.append({"IDmlb": int(mid), "Season": int(season),
                    "Name": row.get("PlayerName") or row.get("Name"),
                    "Pos_fg": row.get("Pos"), "Inn": row.get("Inn"),
                    "DRS": row.get("DRS"), "UZR": row.get("UZR"),
                    "UZR150": row.get("UZR/150"), "OAA": row.get("OAA"),
                    "Def": row.get("Defense")})
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

@st.cache_data(ttl=86400, show_spinner=False)
def get_player_awards(mlbam_id):
    if not mlbam_id:
        return []
    try:
        r = requests.get(
            f"https://statsapi.mlb.com/api/v1/people/{mlbam_id}?hydrate=awards",
            timeout=10
        )
        return r.json().get("people", [{}])[0].get("awards", [])
    except Exception:
        return []

@st.cache_data(ttl=86400, show_spinner=False)
def get_player_career(mlbam_id):
    """Career hitting/pitching totals + bio via MLB Stats API."""
    if not mlbam_id:
        return {}
    out = {}
    try:
        person = requests.get(f"https://statsapi.mlb.com/api/v1/people/{mlbam_id}",
                              headers=MLB_HEADERS, timeout=10).json().get("people",[{}])[0]
        out["debut"]  = person.get("mlbDebutDate","")
        out["pos"]    = (person.get("primaryPosition") or {}).get("abbreviation","")
        out["bats"]   = (person.get("batSide") or {}).get("code","")
        out["throws"] = (person.get("pitchHand") or {}).get("code","")
    except Exception:
        pass
    for grp in ("hitting", "pitching"):
        try:
            sp = requests.get(
                f"https://statsapi.mlb.com/api/v1/people/{mlbam_id}/stats?stats=career&group={grp}",
                headers=MLB_HEADERS, timeout=10).json().get("stats",[{}])[0].get("splits",[])
            if sp:
                out[grp] = sp[0].get("stat", {})
        except Exception:
            pass
    return out

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
# Top banner
st.markdown(
    '<div class="nav-banner">'
    '<span class="nav-title">⚾ <span class="red">BOSWORTH</span> '
    '<span class="blue">ANALYTICS</span> · MLB DASHBOARD</span>'
    '</div>',
    unsafe_allow_html=True,
)
# Horizontal nav — scoped CSS turns this radio into a styled button bar
_NAV_ICONS = {
    "Player Comparison": "⚾",
    "Team Comparison":   "📊",
    "Scouting Report":   "📋",
    "AI Chat":           "🤖",
}
app_mode = st.radio(
    "nav",
    list(_NAV_ICONS.keys()),
    format_func=lambda x: f"{_NAV_ICONS[x]}  {x}",
    horizontal=True,
    key="top_app_mode",
    label_visibility="collapsed",
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

    st.caption("Ask anything — league leaders (hitting, pitching, defense), career comparisons, "
               "records, or analysis. Example: \"Who leads the league in doubles?\" · "
               "\"Who has the most errors?\" · \"Who leads in Outs Above Average?\" · "
               "\"Who's better, Bryce Harper or Mookie Betts?\"")
    chat_season = st.selectbox("Current-season context", [2026, 2025, 2024, 2023], key="chat_season")
    chat_key = tuple(sorted([chat_season]))

    with st.spinner("Loading league data..."):
        try:
            hit_fg = load_mlb_hitting(chat_key)
            try:
                _adv = load_fangraphs_batting(chat_key)
                if not _adv.empty:
                    hit_fg["IDmlb"] = pd.to_numeric(hit_fg["IDmlb"], errors="coerce")
                    _adv["IDmlb"]   = pd.to_numeric(_adv["IDmlb"], errors="coerce")
                    hit_fg = hit_fg.merge(_adv, on=["IDmlb","Season"], how="left")
            except Exception:
                pass
        except Exception:
            hit_fg = pd.DataFrame()
        try:
            pit_fg = load_mlb_pitching(chat_key)
            try:
                _advp = load_fangraphs_pitching(chat_key)
                if not _advp.empty:
                    pit_fg["IDmlb"] = pd.to_numeric(pit_fg["IDmlb"], errors="coerce")
                    _advp["IDmlb"]  = pd.to_numeric(_advp["IDmlb"], errors="coerce")
                    pit_fg = pit_fg.merge(_advp, on=["IDmlb","Season"], how="left")
            except Exception:
                pass
        except Exception:
            pit_fg = pd.DataFrame()
        # ── Fielding / defense (basic via MLB API + advanced via FanGraphs) ──────
        try:
            _fld_raw = load_mlb_fielding(chat_key)
            fld_basic = (_fld_raw.groupby("Name", as_index=False)
                         .agg(E=("E","sum"), A=("A","sum"), PO=("PO","sum"),
                              DP=("DP","sum"), Inn=("Inn","sum")))
        except Exception:
            _fld_raw, fld_basic = pd.DataFrame(), pd.DataFrame()
        try:
            _fadv = load_fangraphs_fielding(chat_key)
            for _c in ["DRS","UZR","UZR150","OAA","Def","Inn"]:
                if _c in _fadv.columns:
                    _fadv[_c] = pd.to_numeric(_fadv[_c], errors="coerce")
            fld_adv = (_fadv.groupby("Name", as_index=False)
                       .agg(DRS=("DRS","sum"), UZR=("UZR","sum"),
                            OAA=("OAA","sum"), Def=("Def","sum"), Inn=("Inn","sum"))
                       if not _fadv.empty else pd.DataFrame())
        except Exception:
            _fadv, fld_adv = pd.DataFrame(), pd.DataFrame()

    def _lb(df, stat, fmt, asc=False, top=12, qualcol=None, qualmin=0):
        """Compact 'stat: Name val, ...' leaderboard string from a league df."""
        if df.empty or stat not in df.columns:
            return ""
        d = df.copy()
        d[stat] = pd.to_numeric(d[stat], errors="coerce")
        if qualcol and qualcol in d.columns:
            d = d[pd.to_numeric(d[qualcol], errors="coerce").fillna(0) >= qualmin]
        d = d[["Name", stat]].dropna().sort_values(stat, ascending=asc).head(top)
        if d.empty:
            return ""
        return f"{stat}: " + ", ".join(f"{n} {fmt.format(v)}" for n, v in zip(d["Name"], d[stat]))

    _hit_lbs = [
        _lb(hit_fg, "HR",  "{:.0f}"),                 _lb(hit_fg, "RBI", "{:.0f}"),
        _lb(hit_fg, "2B",  "{:.0f}"),                 _lb(hit_fg, "3B",  "{:.0f}"),
        _lb(hit_fg, "H",   "{:.0f}"),                 _lb(hit_fg, "SB",  "{:.0f}"),
        _lb(hit_fg, "AVG", "{:.3f}", qualcol="PA", qualmin=180),
        _lb(hit_fg, "OBP", "{:.3f}", qualcol="PA", qualmin=180),
        _lb(hit_fg, "SLG", "{:.3f}", qualcol="PA", qualmin=180),
        _lb(hit_fg, "OPS", "{:.3f}", qualcol="PA", qualmin=180),
        _lb(hit_fg, "wRC+","{:.0f}", qualcol="PA", qualmin=180),
        _lb(hit_fg, "WAR", "{:.1f}"),
    ]
    _pit_lbs = [
        _lb(pit_fg, "WAR", "{:.1f}"),                 _lb(pit_fg, "SO",  "{:.0f}"),
        _lb(pit_fg, "W",   "{:.0f}"),                 _lb(pit_fg, "SV",  "{:.0f}"),
        _lb(pit_fg, "IP",  "{:.1f}"),
        _lb(pit_fg, "ERA", "{:.2f}", asc=True, qualcol="IP", qualmin=40),
        _lb(pit_fg, "WHIP","{:.2f}", asc=True, qualcol="IP", qualmin=40),
        _lb(pit_fg, "FIP", "{:.2f}", asc=True, qualcol="IP", qualmin=40),
        _lb(pit_fg, "K/9", "{:.1f}", qualcol="IP", qualmin=40),
        _lb(pit_fg, "K%",  "{:.1f}", qualcol="IP", qualmin=40),
    ]
    _fld_lbs = [
        _lb(fld_basic, "E",  "{:.0f}"),               # most errors
        _lb(fld_basic, "A",  "{:.0f}"),               # most assists
        _lb(fld_basic, "PO", "{:.0f}"),               # most putouts
        _lb(fld_basic, "DP", "{:.0f}"),               # most double plays
        _lb(fld_adv,   "DRS","{:.0f}", qualcol="Inn", qualmin=200),  # best (most runs saved)
        _lb(fld_adv,   "OAA","{:.0f}", qualcol="Inn", qualmin=200),  # outs above average
        _lb(fld_adv,   "UZR","{:.1f}", qualcol="Inn", qualmin=200),
        _lb(fld_adv,   "Def","{:.1f}", qualcol="Inn", qualmin=200),  # total defensive runs
    ]
    _hit_block = "\n".join(x for x in _hit_lbs if x) or "unavailable"
    _pit_block = "\n".join(x for x in _pit_lbs if x) or "unavailable"
    _fld_block = "\n".join(x for x in _fld_lbs if x) or "unavailable"

    sys_prompt = f"""You are an expert MLB analytics assistant for Bosworth Analytics.
Answer ANY baseball question: current-season league leaders, career comparisons, all-time
or active records, team and historical analysis. Be concise and analytical, back claims with
numbers, and give a clear verdict on "who's better" questions (weigh peak, career value, and role).
Never fabricate a stat — if you are not sure, say so.

CURRENT SEASON = {chat_season}. The live {chat_season} regular-season leaderboards below come from
the MLB Stats API + FanGraphs (top 12 each; rate stats are qualified). Use THESE numbers for any
"who leads / most this season / league leader" question rather than your training data.

HITTING LEADERS ({chat_season}):
{_hit_block}

PITCHING LEADERS ({chat_season}):
{_pit_block}

FIELDING / DEFENSE LEADERS ({chat_season}):
{_fld_block}
(E=errors, A=assists, PO=putouts, DP=double plays — counting totals across all positions.
DRS=Defensive Runs Saved, OAA=Outs Above Average, UZR=Ultimate Zone Rating, Def=total
defensive runs; higher is better for DRS/OAA/UZR/Def. More errors = worse defense.)

When the user names specific players, a "PLAYERS REFERENCED" block below provides their real
CAREER totals (MLB Stats API) and current-season line. For "compare career metrics" questions,
USE those career numbers directly — build the comparison table from them and give a verdict. Do
NOT say you lack the data or fall back to estimates when a career block is provided.

For all-time leaders, awards, and Hall-of-Fame questions where no block is provided, use your
baseball knowledge. Never invent a number with a "~" estimate if real data is in the block."""

    if "chat_history" not in st.session_state:
        st.session_state.chat_history = []

    for msg in st.session_state.chat_history:
        with st.chat_message(msg["role"],
                             avatar="🧑" if msg["role"] == "user" else "⚾"):
            st.markdown(msg["content"])

    def _fmtnum(v):
        try:
            f = float(v)
            if f == int(f): return str(int(f))
            return f"{f:.3f}" if abs(f) < 1 else f"{f:.2f}"
        except Exception:
            return str(v)

    def _stats_line(name):
        out = []
        if not hit_fg.empty and name in set(hit_fg["Name"]):
            r = hit_fg[hit_fg["Name"] == name].sort_values("Season").iloc[-1]
            ks = [k for k in ["AVG","OBP","SLG","OPS","HR","2B","RBI","SB","wRC+","WAR","BB%","K%"]
                  if k in r.index and pd.notna(r.get(k))]
            if ks: out.append("hitting " + ", ".join(f"{k}={_fmtnum(r[k])}" for k in ks))
        if not pit_fg.empty and name in set(pit_fg["Name"]):
            r = pit_fg[pit_fg["Name"] == name].sort_values("Season").iloc[-1]
            ks = [k for k in ["W","L","SV","IP","ERA","WHIP","K/9","K%","BB%","FIP","WAR"]
                  if k in r.index and pd.notna(r.get(k))]
            if ks: out.append("pitching " + ", ".join(f"{k}={_fmtnum(r[k])}" for k in ks))
        if not fld_basic.empty and name in set(fld_basic["Name"]):
            r = fld_basic[fld_basic["Name"] == name].iloc[0]
            dparts = [f"{k}={_fmtnum(r[k])}" for k in ["E","A","PO","DP"]
                      if k in r.index and pd.notna(r.get(k))]
            if not fld_adv.empty and name in set(fld_adv["Name"]):
                ra = fld_adv[fld_adv["Name"] == name].iloc[0]
                dparts += [f"{k}={_fmtnum(ra[k])}" for k in ["DRS","OAA","UZR","Def"]
                           if k in ra.index and pd.notna(ra.get(k))]
            if dparts: out.append("fielding " + ", ".join(dparts))
        return f"{name} ({chat_season}): " + " | ".join(out) if out else ""

    def _mlbam_for(name):
        for df in (hit_fg, pit_fg):
            if not df.empty and "IDmlb" in df.columns and name in set(df["Name"]):
                v = df[df["Name"] == name]["IDmlb"].iloc[0]
                try:
                    if pd.notna(v): return int(v)
                except Exception:
                    pass
        return None

    def _career_str(name):
        mid = _mlbam_for(name)
        if not mid: return ""
        c = get_player_career(mid)
        if not c: return ""
        segs = []
        h = c.get("hitting")
        if h:
            ks = [("G","gamesPlayed"),("PA","plateAppearances"),("AB","atBats"),("H","hits"),
                  ("AVG","avg"),("OBP","obp"),("SLG","slg"),("OPS","ops"),("HR","homeRuns"),
                  ("RBI","rbi"),("SB","stolenBases"),("BB","baseOnBalls"),("SO","strikeOuts")]
            seg = ", ".join(f"{l}={h.get(k)}" for l,k in ks if h.get(k) not in (None,""))
            if seg: segs.append("career hitting: " + seg)
        p = c.get("pitching")
        if p:
            ks = [("G","gamesPlayed"),("GS","gamesStarted"),("W","wins"),("L","losses"),
                  ("SV","saves"),("IP","inningsPitched"),("ERA","era"),("WHIP","whip"),
                  ("SO","strikeOuts"),("HR","homeRuns")]
            seg = ", ".join(f"{l}={p.get(k)}" for l,k in ks if p.get(k) not in (None,""))
            if seg: segs.append("career pitching: " + seg)
        if not segs: return ""
        meta = []
        if c.get("debut"): meta.append(f"MLB debut {c['debut']}")
        if c.get("pos"):   meta.append(c["pos"])
        head = name + (f" ({'; '.join(meta)})" if meta else "")
        return head + " — " + " | ".join(segs)

    def _mentioned_names(msg):
        ml = msg.lower()
        names = set()
        for df in (hit_fg, pit_fg, fld_basic):
            if not df.empty: names |= set(df["Name"].dropna())
        matched = []
        for name in names:
            toks = name.lower().split()
            if len(toks) < 2: continue
            first, last = toks[0], toks[-1]
            # full name present, OR first+last both present (handles short last names like "Lee"),
            # OR a distinctive last name on its own
            if name.lower() in ml or (first in ml and last in ml) or (len(last) >= 5 and last in ml):
                matched.append(name)
        return list(dict.fromkeys(matched))[:8]

    def _find_mentioned_players(names):
        out = []
        for nm in names:
            block = [x for x in (_career_str(nm), _stats_line(nm)) if x]
            if block: out.append("\n".join(block))
        return out

    def _career_table_md(names):
        """Deterministic, accurate career-stats table straight from the MLB API."""
        data = {}
        for nm in names:
            mid = _mlbam_for(nm)
            if mid:
                c = get_player_career(mid)
                if c: data[nm] = c
        if not data:
            return ""
        cols = list(data.keys())
        blocks = []
        def _table(title, rows, grp):
            present = [nm for nm in cols if data[nm].get(grp)]
            if len(present) < 1 or (len(cols) >= 2 and len(present) < 2):
                return ""
            hdr = "| Metric | " + " | ".join(present) + " |"
            sep = "|" + "---|" * (len(present) + 1)
            lines = [f"**{title}**", "", hdr, sep]
            for lab, key in rows:
                vals = [str((data[nm].get(grp) or {}).get(key, "—")) for nm in present]
                lines.append(f"| {lab} | " + " | ".join(vals) + " |")
            return "\n".join(lines)
        _hit_rows = [("Games","gamesPlayed"),("PA","plateAppearances"),("AVG","avg"),
                     ("OBP","obp"),("SLG","slg"),("OPS","ops"),("HR","homeRuns"),
                     ("RBI","rbi"),("SB","stolenBases"),("BB","baseOnBalls"),("SO","strikeOuts")]
        _pit_rows = [("Games","gamesPlayed"),("GS","gamesStarted"),("W","wins"),("L","losses"),
                     ("SV","saves"),("IP","inningsPitched"),("ERA","era"),("WHIP","whip"),
                     ("SO","strikeOuts"),("HR","homeRuns")]
        for t, r, g in [("Career Hitting (official MLB stats)", _hit_rows, "hitting"),
                        ("Career Pitching (official MLB stats)", _pit_rows, "pitching")]:
            tb = _table(t, r, g)
            if tb: blocks.append(tb)
        return "\n\n".join(blocks)

    if prompt := st.chat_input("Ask any baseball question..."):
        st.session_state.chat_history.append({"role": "user", "content": prompt})
        with st.chat_message("user", avatar="🧑"):
            st.markdown(prompt)

        with st.chat_message("assistant", avatar="⚾"):
            with st.spinner("Analyzing..."):
                try:
                    _names = _mentioned_names(prompt)
                    extra = _find_mentioned_players(_names)
                    _table_md = _career_table_md(_names) if _names else ""
                    dynamic_sys = sys_prompt
                    if extra:
                        dynamic_sys += "\n\nPLAYERS REFERENCED (real career totals + current line):\n\n" + "\n\n".join(extra)
                    if _table_md:
                        dynamic_sys += ("\n\nAn ACCURATE career stats table is already being shown "
                                        "to the user above your reply. Do NOT output your own stats "
                                        "table or restate the raw numbers. Give a short written "
                                        "verdict and analysis that is fully consistent with those "
                                        "exact numbers (e.g., note who leads in HR, OPS, etc.).")
                    client = _anthropic.Anthropic(api_key=_ANT_KEY)
                    resp = client.messages.create(
                        model="claude-haiku-4-5-20251001",
                        max_tokens=900,
                        system=dynamic_sys,
                        messages=[{"role": m["role"], "content": m["content"]}
                                  for m in st.session_state.chat_history],
                    )
                    answer = resp.content[0].text
                except Exception as e:
                    answer = f"Error connecting to AI: {e}"
                    _table_md = ""
                final = (f"{_table_md}\n\n---\n\n{answer}" if _table_md else answer)
                st.markdown(final)
                st.session_state.chat_history.append({"role": "assistant", "content": final})

    if st.session_state.chat_history:
        if st.button("Clear Chat", key="clear_chat"):
            st.session_state.chat_history = []
            st.rerun()
    st.stop()

# ── Helper functions (defined early so Scouting Report can use them) ───────────
def p_seasons(name): return all_fg[all_fg["Name"]==name].sort_values("Season")
def p_latest(name):
    d = p_seasons(name); return d.iloc[-1] if not d.empty else None
def p_mlbam(name):
    r = p_latest(name)
    return int(r["IDmlb"]) if r is not None and "IDmlb" in r.index and pd.notna(r.get("IDmlb")) else None
def safe(val, fmt="{:.3f}"):
    try: return fmt.format(float(val)) if val is not None and pd.notna(val) else "N/A"
    except: return "N/A"

def _compute_scouting_grades(player):
    row = p_latest(player)
    if row is None: return None
    def gv(col, default=0.0):
        v = row.get(col)
        return float(v) if v is not None and pd.notna(v) else default
    def clamp(x): return max(20, min(80, round(x)))
    if mode == "Hitters":
        wrc = gv("wRC+", 100); slg = gv("SLG", 0.400)
        avg = gv("AVG", 0.248); sb  = gv("SB", 0); g = gv("G", 100)
        iso = slg - avg; sbr = sb / max(g, 1) * 162
        return {"Hit": clamp(50+(wrc-100)*0.30), "Power": clamp(20+iso*200),
                "Speed": clamp(35+sbr*0.65), "Field": 50, "Arm": 50}
    else:
        bb=gv("BB%",8.5); k=gv("K%",23.0); k9=gv("K/9",9.0)
        ip=gv("IP",50.0); gs=gv("GS",0); g=gv("G",20)
        ipg=ip/max(g,1); stamina=clamp(ipg*11) if gs>0 else clamp(35+ipg*5)
        velo_grade=50
        if HAS_PB:
            mid=p_mlbam(player)
            if mid:
                for s in sorted(sel_seasons, reverse=True):
                    raw=get_statcast_pitcher_raw(mid,s)
                    if not raw.empty and "release_speed" in raw.columns:
                        fb=raw[raw["pitch_type"].isin(["FF","SI"])]["release_speed"].dropna()
                        if len(fb)<5: fb=raw[raw["pitch_type"].isin(["FF","SI","FC"])]["release_speed"].dropna()
                        if len(fb)>=5: velo_grade=clamp(50+(fb.mean()-93.5)*5); break
        return {"FB Velo": velo_grade, "Command": clamp(50+(8.5-bb)*2.5),
                "Stamina": stamina, "Deception": clamp(50+(k-23.0)*1.5),
                "Arm Strength": clamp(50+(k9-9.0)*3.0)}

# ════════════════════════════════════════════════════════════════════════════════
# SCOUTING REPORT MODE
# ════════════════════════════════════════════════════════════════════════════════
if app_mode == "Scouting Report":

    def _gc(g):
        if g>=70: return "#00C851","#004d1f","#00C851"
        if g>=60: return "#2ecc71","#0a5c2a","#2ecc71"
        if g>=55: return "#8BC34A","#2d5000","#8BC34A"
        if g>=50: return "#8B9EC4","#1A2E47","#8B9EC4"
        if g>=45: return "#FFA726","#5c2d00","#FFA726"
        if g>=40: return "#EF5350","#5c0000","#EF5350"
        return "#B71C1C","#3a0000","#B71C1C"

    def _grade_bar(tool, val):
        pct = round((val - 20) / 60 * 100)
        color, c1, c2 = _gc(val)
        lbl = grade_label(val)
        return (
            f'<div style="display:flex;align-items:center;gap:12px;padding:10px 0;'
            f'border-bottom:1px solid #1A2E47">'
            f'<span style="width:115px;color:#8B9EC4;font-size:.7rem;font-weight:700;'
            f'text-transform:uppercase;letter-spacing:.8px;flex-shrink:0">{tool}</span>'
            f'<div style="width:36px;height:36px;border-radius:7px;background:{color}18;'
            f'border:2px solid {color}88;display:flex;align-items:center;justify-content:center;flex-shrink:0">'
            f'<span style="color:{color};font-weight:900;font-size:1.05rem;font-family:monospace">{val}</span></div>'
            f'<div style="flex:1;height:8px;background:#0A1525;border-radius:4px;overflow:hidden">'
            f'<div style="width:{pct}%;height:100%;border-radius:4px;'
            f'background:linear-gradient(90deg,{c1},{c2})"></div></div>'
            f'<span style="width:120px;color:{color};font-size:.68rem;font-weight:700;'
            f'text-transform:uppercase;letter-spacing:.6px;text-align:right;flex-shrink:0">{lbl}</span>'
            f'</div>'
        )

    def _ofp_role(g, grades=None):
        if mode == "Hitters":
            if   g>=70: tier = "Perennial All-Star"
            elif g>=65: tier = "All-Star Regular"
            elif g>=60: tier = "Above-Avg Everyday Regular"
            elif g>=55: tier = "Solid Everyday Regular"
            elif g>=50: tier = "Average Regular / Platoon"
            elif g>=45: tier = "Bench Bat / Fringe Regular"
            elif g>=40: tier = "Bench / Org Depth"
            else:       tier = "Org Depth"
            tags = []
            if grades:
                hit = grades.get("Hit", 50); pwr = grades.get("Power", 50)
                spd = grades.get("Speed", 50)
                if pwr >= 60: tags.append("home-run power")
                elif pwr >= 55: tags.append("doubles power")
                if hit >= 60: tags.append("plus contact hitter")
                elif hit >= 55: tags.append("solid contact")
                if spd >= 60: tags.append("plus speed")
                if not tags:
                    _top = max([("contact", hit), ("power", pwr), ("speed", spd)],
                               key=lambda x: x[1])
                    tags.append({"contact": "contact-oriented bat",
                                 "power": "power-leaning bat",
                                 "speed": "speed/athleticism"}[_top[0]])
            return f"{tier} · {', '.join(tags)}" if tags else tier
        if g>=70: return "Franchise Cornerstone"
        if g>=65: return "No. 1 Starter / All-Star"
        if g>=60: return "No. 2 Starter / Above Avg Regular"
        if g>=55: return "No. 3 Starter / Solid Regular"
        if g>=50: return "No. 4 Starter / Platoon Player"
        if g>=45: return "No. 5 / Fringe Regular"
        if g>=40: return "Reliever / Bench Piece"
        return "AAAA / Org Depth"

    def _stat_table_html(rows, headers):
        th = "".join(
            f'<th style="padding:9px 14px;text-align:center;font-size:.68rem;'
            f'letter-spacing:.9px;color:#F4F8FF;font-weight:700;text-transform:uppercase;'
            f'white-space:nowrap">{h}</th>'
            for h in headers
        )
        body = ""
        for i, row_vals in enumerate(rows):
            bg = "#0F1E32" if i % 2 == 0 else "#0A1525"
            cells = "".join(
                f'<td style="padding:8px 14px;text-align:center;font-size:.82rem;'
                f'color:#F4F8FF;border-bottom:1px solid #1A2E47;white-space:nowrap">{v}</td>'
                for v in row_vals
            )
            body += f'<tr style="background:{bg}">{cells}</tr>'
        return (
            f'<div style="overflow-x:auto;border-radius:10px;border:1px solid #1A2E47;margin-bottom:20px">'
            f'<table style="width:100%;border-collapse:collapse">'
            f'<thead><tr style="background:#C8102E">{th}</tr></thead>'
            f'<tbody>{body}</tbody>'
            f'</table></div>'
        )

    def _gameplan_bullets(player, grades, latest_row):
        bullets = []
        def gf(col, default):
            v = latest_row.get(col)
            try: return float(v) if v is not None and pd.notna(v) else default
            except: return default

        if mode == "Pitchers":
            velo_g = grades.get("FB Velo", 50)
            cmd_g  = grades.get("Command", 50)
            dec_g  = grades.get("Deception", 50)
            stam_g = grades.get("Stamina", 50)
            approx_velo = round(93.5 + (velo_g - 50) / 5.0, 1)
            bb_pct = gf("BB%", 8.5)
            k_pct  = gf("K%", 23.0)
            era    = gf("ERA", 4.00)
            if velo_g >= 60:
                bullets.append(f"Elite fastball (~{approx_velo} mph) — don't sit dead-red. Expect FB hard in on the hands. Look for off-speed in two-strike counts.")
            elif velo_g >= 55:
                bullets.append(f"Above-average heater (~{approx_velo} mph) — be ready early in the count. Don't be late on the fastball.")
            else:
                bullets.append(f"Below-average velocity (~{approx_velo} mph) — attack the fastball aggressively in hitter's counts. Don't let him work soft stuff deep into at-bats.")
            if cmd_g >= 60:
                bullets.append(f"Elite command ({bb_pct:.1f}% BB rate) — he paints the corners all game. Expand the zone early; don't let strikes go to waste.")
            elif cmd_g >= 50:
                bullets.append(f"Average command ({bb_pct:.1f}% BB rate) — work counts; he will nibble when behind and may miss over the plate in favorable counts.")
            else:
                bullets.append(f"Below-average command ({bb_pct:.1f}% BB rate) — take pitches and work walks. Force him into the zone; don't chase early.")
            if dec_g >= 60:
                bullets.append(f"High strikeout stuff ({k_pct:.1f}% K rate) — shorten up with two strikes and protect the plate.")
            elif dec_g <= 44:
                bullets.append(f"Below-average strikeout rate ({k_pct:.1f}% K rate) — put the ball in play. Don't give up at-bats; he lives off contact outs.")
            else:
                bullets.append(f"Average swing-and-miss ({k_pct:.1f}% K rate) — be selective but don't over-protect with two strikes.")
            if stam_g <= 44:
                bullets.append("Pitch-count sensitive — grind deep into at-bats early. Get to the bullpen by the 5th.")
            elif stam_g >= 60:
                bullets.append("Workhorse starter — expect 6–7 IP. No quick hook; bring your best AB every time through the lineup.")
            if era <= 3.25:
                bullets.append(f"Elite ERA ({era:.2f}) — situational hitting is critical. Drive in runners; don't swing for the fences.")
            elif era >= 5.00:
                bullets.append(f"High ERA ({era:.2f}) — capitalize on baserunners. He gives up big innings; stay patient and the runs will come.")
        else:
            hit_g   = grades.get("Hit", 50)
            pow_g   = grades.get("Power", 50)
            spd_g   = grades.get("Speed", 50)
            avg_v   = gf("AVG", .248)
            slg_v   = gf("SLG", .400)
            sb_v    = gf("SB", 0)
            wrc     = gf("wRC+", 100)
            if pow_g >= 60:
                bullets.append(f"Plus-power hitter (.{int(slg_v*1000):03d} SLG) — do not miss over the plate. Work him away and down. Never leave a breaking ball hanging.")
            elif pow_g <= 44:
                bullets.append(f"Below-average power (.{int(slg_v*1000):03d} SLG) — challenge him with hard stuff up. He beats you with contact, not the long ball.")
            else:
                bullets.append(f"Average raw power (.{int(slg_v*1000):03d} SLG) — respect gap power. Don't pattern him fastball-only and don't miss in the zone.")
            if hit_g >= 60:
                bullets.append(f"Plus contact ability (.{int(avg_v*1000):03d} AVG) — throw your best stuff for strikes. Don't nibble; he'll make you pay for walks.")
            elif hit_g <= 44:
                bullets.append(f"Below-average bat (.{int(avg_v*1000):03d} AVG) — expand the chase zone down and away. He'll fish for breaking balls out of the zone.")
            else:
                bullets.append(f"Average hitter (.{int(avg_v*1000):03d} AVG) — mix locations and change eye levels. Don't be predictable.")
            if spd_g >= 60:
                bullets.append(f"Premium stolen base threat ({int(sb_v):.0f} SB) — keep him close at all times. Vary slide step and pickoff timing.")
            elif spd_g >= 50:
                bullets.append(f"Above-average runner ({int(sb_v):.0f} SB) — be mindful with men on. Control the running game.")
            else:
                bullets.append("Below-average speed — no running game threat. Focus entirely on pitch execution.")
            if wrc >= 130:
                bullets.append(f"Elite wRC+ ({int(wrc)}) — treat every at-bat as high-leverage. No free passes; make him earn it.")
            elif wrc <= 80:
                bullets.append(f"Below-average production (wRC+ {int(wrc)}) — attack early in the count. Don't give him a free look.")
        return bullets

    # ── Controls ────────────────────────────────────────────────────────────────
    _sr_c1, _sr_c2 = st.columns([1, 3])
    with _sr_c1:
        mode = st.radio("Type", ["Hitters","Pitchers"], horizontal=True, key="sr_mode")
    with _sr_c2:
        _sr_seas = st.pills("Seasons", ALL_SEASONS, default=ALL_SEASONS, selection_mode="multi", key="sr_seasons")
        sel_seasons = tuple(sorted(_sr_seas)) if _sr_seas else (2026,)

    with st.spinner("Loading players..."):
        all_fg = load_mlb_hitting(sel_seasons) if mode=="Hitters" else load_mlb_pitching(sel_seasons)
        try:
            _sr_adv = load_fangraphs_batting(sel_seasons) if mode=="Hitters" else load_fangraphs_pitching(sel_seasons)
            if not _sr_adv.empty:
                all_fg["IDmlb"]  = pd.to_numeric(all_fg["IDmlb"],  errors="coerce")
                _sr_adv["IDmlb"] = pd.to_numeric(_sr_adv["IDmlb"], errors="coerce")
                all_fg = all_fg.merge(_sr_adv, on=["IDmlb","Season"], how="left")
        except Exception: pass

    _plist = sorted(all_fg["Name"].dropna().unique().tolist()) if not all_fg.empty else []
    _def_sr = next((p for p in _plist if "Ohtani" in p), _plist[0] if _plist else "")
    sr_player = st.selectbox(
        "Select Player", _plist,
        index=_plist.index(_def_sr) if _def_sr in _plist else 0,
        key="sr_player"
    )
    if not sr_player:
        st.warning("No players found. Try adjusting the seasons.")
        st.stop()

    # ── Load player data ─────────────────────────────────────────────────────────
    row    = p_latest(sr_player)
    mid    = p_mlbam(sr_player)
    team   = row.get("Team", "") if row is not None else ""
    hs_url = (
        f"https://img.mlbstatic.com/mlb-photos/image/upload/"
        f"d_people:generic:headshot:67:current.png"
        f"/w_213,q_auto:best/v1/people/{mid}/headshot/67/current"
    ) if mid else ""
    grades = _compute_scouting_grades(sr_player)
    ofp    = round(sum(grades.values()) / len(grades)) if grades else 50
    ofp_c, _, _ = _gc(ofp)
    sn_df  = p_seasons(sr_player)
    _seas_str = " / ".join(str(s) for s in sorted(sel_seasons))

    # Pre-load Statcast once (cached) — shared by Spray Chart + Zone Analysis
    _sr_sc_raw, _sr_sc_season = pd.DataFrame(), None
    if mid and HAS_PB:
        for _zss in sorted(sel_seasons, reverse=True):
            _sr_sc_raw = (get_statcast_pitcher_raw(mid, _zss) if mode == "Pitchers"
                          else get_statcast_batter_raw(mid, _zss))
            if not _sr_sc_raw.empty:
                _sr_sc_season = _zss; break

    # ── Report header banner ──────────────────────────────────────────────────────
    def _qs(key, fmt):
        v = row.get(key) if row is not None else None
        return safe(v, fmt)

    if mode == "Pitchers":
        _qs_items = [
            ("ERA",  _qs("ERA",  "{:.2f}"), "#F4F8FF"),
            ("WHIP", _qs("WHIP", "{:.2f}"), "#F4F8FF"),
            ("K%",   _qs("K%",   "{:.1f}") + "%", "#00BFFF"),
            ("FIP",  _qs("FIP",  "{:.2f}"), "#C4A962"),
        ]
    else:
        _qs_items = [
            ("AVG",  _qs("AVG",  "{:.3f}"), "#F4F8FF"),
            ("OPS",  _qs("OPS",  "{:.3f}"), "#F4F8FF"),
            ("wRC+", _qs("wRC+", "{:.0f}"), "#00BFFF"),
            ("HR",   _qs("HR",   "{:.0f}"), "#C4A962"),
        ]

    _qs_html = "".join(
        f'<div style="text-align:center;background:#0A1525;border-radius:10px;'
        f'padding:12px 18px;border:1px solid #1A2E47;min-width:72px">'
        f'<div style="font-size:1.45rem;font-weight:900;color:{vc};font-family:monospace;line-height:1">{vv}</div>'
        f'<div style="font-size:.62rem;color:#8B9EC4;text-transform:uppercase;letter-spacing:.9px;margin-top:3px">{vk}</div>'
        f'</div>'
        for vk, vv, vc in _qs_items
    )

    _img_tag = (
        f'<img src="{hs_url}" style="width:88px;height:88px;border-radius:50%;'
        f'border:3px solid #C8102E;object-fit:cover;flex-shrink:0;'
        f'box-shadow:0 0 18px #C8102E44" onerror="this.style.display=\'none\'">'
    ) if hs_url else (
        f'<div style="width:88px;height:88px;border-radius:50%;background:#1A2E47;'
        f'border:3px solid #C8102E;flex-shrink:0"></div>'
    )

    st.markdown(
        f'<div style="background:linear-gradient(135deg,#0F1E32 55%,#121F35);'
        f'border-top:4px solid #C8102E;border:1px solid #1A2E47;border-top-width:4px;'
        f'border-radius:14px;padding:24px 28px;margin:10px 0 22px">'
        f'<div style="display:flex;justify-content:space-between;align-items:center;'
        f'flex-wrap:wrap;gap:18px">'
        f'<div style="display:flex;align-items:center;gap:20px">'
        f'{_img_tag}'
        f'<div>'
        f'<div style="font-size:.62rem;font-weight:700;color:#C8102E;letter-spacing:2.5px;'
        f'text-transform:uppercase;margin-bottom:5px">⚾ Advance Scouting Report</div>'
        f'<div style="font-size:1.75rem;font-weight:900;color:#F4F8FF;line-height:1.1;'
        f'letter-spacing:.3px">{sr_player}</div>'
        f'<div style="font-size:.85rem;color:#8B9EC4;margin-top:5px">'
        f'{team}&nbsp;&nbsp;·&nbsp;&nbsp;{"Pitcher" if mode=="Pitchers" else "Hitter"}'
        f'&nbsp;&nbsp;·&nbsp;&nbsp;{_seas_str}</div>'
        f'</div></div>'
        f'<div style="display:flex;gap:12px;flex-wrap:wrap">{_qs_html}</div>'
        f'</div></div>',
        unsafe_allow_html=True
    )

    # ── MLB Rankings (right under player card) ───────────────────────────────────
    st.markdown('<div class="section-header">MLB Rankings</div>', unsafe_allow_html=True)
    _rank_season = int(sn_df["Season"].max()) if not sn_df.empty else int(max(sel_seasons))
    _rank_df = all_fg[all_fg["Season"] == _rank_season].copy()
    if mode == "Pitchers":
        _rq = pd.to_numeric(_rank_df.get("IP", pd.Series(dtype=float)), errors="coerce").fillna(0)
        _rank_df = _rank_df[_rq >= 20]
        _rank_defs = [
            ("ERA","ERA",True,"{:.2f}"),("WHIP","WHIP",True,"{:.2f}"),
            ("K%","K%",False,"{:.1f}%"),("BB%","BB%",True,"{:.1f}%"),
            ("K/9","K/9",False,"{:.1f}"),("K-BB%","K-BB%",False,"{:.1f}%"),
            ("FIP","FIP",True,"{:.2f}"),("IP","IP",False,"{:.1f}"),
            ("WAR","WAR",False,"{:.1f}"),
        ]
    else:
        _rq = pd.to_numeric(_rank_df.get("PA", pd.Series(dtype=float)), errors="coerce").fillna(0)
        _rank_df = _rank_df[_rq >= 100]
        _rank_defs = [
            ("AVG","AVG",False,"{:.3f}"),("OBP","OBP",False,"{:.3f}"),
            ("SLG","SLG",False,"{:.3f}"),("OPS","OPS",False,"{:.3f}"),
            ("HR","HR",False,"{:.0f}"),("RBI","RBI",False,"{:.0f}"),
            ("SB","SB",False,"{:.0f}"),("wRC+","wRC+",False,"{:.0f}"),
            ("K%","K%",True,"{:.1f}%"),("BB%","BB%",False,"{:.1f}%"),
            ("WAR","WAR",False,"{:.1f}"),
        ]
    _rank_cards = []
    for _sc2, _sn2, _lib2, _fmt2 in _rank_defs:
        if _sc2 not in _rank_df.columns: continue
        _tmp2 = (_rank_df[["Name",_sc2]].dropna()
                 .sort_values(_sc2, ascending=_lib2).reset_index(drop=True))
        _pm2 = _tmp2[_tmp2["Name"] == sr_player]
        if _pm2.empty: continue
        _val2 = float(_pm2.iloc[0][_sc2])
        _rpos2 = int(_pm2.index[0]) + 1
        _tot2  = len(_tmp2)
        _pct2  = round((_tot2 - _rpos2) / _tot2 * 100)
        _rank_cards.append((_sn2, _val2, _rpos2, _tot2, _pct2, _fmt2))

    def _pct_clr(p):
        if p >= 90: return "#00C851"
        if p >= 75: return "#8BC34A"
        if p >= 50: return "#8B9EC4"
        if p >= 25: return "#FFA726"
        return "#EF5350"

    if _rank_cards:
        _rc_html = '<div style="display:flex;flex-wrap:wrap;gap:10px;margin-bottom:22px">'
        for _sn2, _val2, _rpos2, _tot2, _pct2, _fmt2 in _rank_cards:
            _cc = _pct_clr(_pct2)
            _vd = _fmt2.format(_val2)
            _rc_html += (
                f'<div style="background:#0F1E32;border:1px solid #1A2E47;border-top:3px solid {_cc};'
                f'border-radius:10px;padding:13px 16px;min-width:110px;flex:1">'
                f'<div style="font-size:.6rem;font-weight:700;color:#C8102E;'
                f'letter-spacing:2px;text-transform:uppercase;margin-bottom:6px">{_sn2}</div>'
                f'<div style="font-size:1.55rem;font-weight:900;color:#F4F8FF;'
                f'font-family:monospace;line-height:1.1">{_vd}</div>'
                f'<div style="font-size:.7rem;color:{_cc};font-weight:700;margin-top:6px">'
                f'#{_rpos2} of {_tot2}</div>'
                f'<div style="margin-top:5px;background:#0A1525;border-radius:3px;height:4px">'
                f'<div style="width:{_pct2}%;background:{_cc};height:4px;border-radius:3px"></div></div>'
                f'<div style="font-size:.6rem;color:#8B9EC4;margin-top:3px">'
                f'{_pct2}th pct · {_rank_season}</div></div>'
            )
        _rc_html += '</div>'
        st.markdown(_rc_html, unsafe_allow_html=True)
    else:
        st.markdown(
            '<div style="color:#8B9EC4;font-size:.85rem;padding:8px 0">'
            'No ranking data available (need ≥20 IP / ≥100 PA in selected season).</div>',
            unsafe_allow_html=True
        )

    # ── Spray Chart — Hitters (right under rankings) ─────────────────────────────
    if mode == "Hitters" and not _sr_sc_raw.empty:
        _SC_HIT_SET = {"single","double","triple","home_run"}
        _EV_CLR_T = {"home_run":"#C8102E","triple":"#FFD700","double":"#FFA726","single":"#00BFFF"}
        _sp_df = _sr_sc_raw[
            _sr_sc_raw["hc_x"].notna() & _sr_sc_raw["hc_y"].notna() &
            _sr_sc_raw["events"].notna()
        ].copy()
        _sp_in = _sp_df[_sp_df["events"].isin(
            _SC_HIT_SET | {"field_out","grounded_into_double_play","double_play",
                           "sac_fly","fielders_choice_out","force_out"}
        )]
        if not _sp_in.empty:
            st.markdown('<div class="section-header">Spray Chart</div>', unsafe_allow_html=True)
            _sp_hits = []
            for _, _spr in _sp_in.iterrows():
                _shx = _spr.get("hc_x"); _shy = _spr.get("hc_y")
                if pd.isna(_shx) or pd.isna(_shy): continue
                _sp_hits.append({"x": round(float(_shx),1), "y": round(float(_shy),1),
                                  "c": _EV_CLR_T.get(_spr.get("events",""),"#1A2E47"),
                                  "e": str(_spr.get("events",""))})
            _sp_js  = json.dumps(_sp_hits)
            _sp_n1  = sum(1 for h in _sp_hits if h["e"]=="single")
            _sp_n2  = sum(1 for h in _sp_hits if h["e"]=="double")
            _sp_n3  = sum(1 for h in _sp_hits if h["e"]=="triple")
            _sp_nhr = sum(1 for h in _sp_hits if h["e"]=="home_run")
            _sp_no  = sum(1 for h in _sp_hits if h["e"] not in _EV_CLR_T)
            _sp_html = f"""<!DOCTYPE html><html><head>
<style>html,body{{margin:0;padding:0;background:{CARD_BG};font-family:'Inter',sans-serif}}
#sc{{display:block;margin:0 auto}}
.leg{{display:flex;gap:14px;justify-content:center;padding:5px 0;font-size:11px;color:#8B9EC4;flex-wrap:wrap}}
.dot{{width:9px;height:9px;border-radius:50%;display:inline-block;margin-right:4px;vertical-align:middle}}
</style></head><body>
<canvas id="sc" width="380" height="360"></canvas>
<div class="leg">
  <span><span class="dot" style="background:#00BFFF"></span>1B ({_sp_n1})</span>
  <span><span class="dot" style="background:#FFA726"></span>2B ({_sp_n2})</span>
  <span><span class="dot" style="background:#FFD700"></span>3B ({_sp_n3})</span>
  <span><span class="dot" style="background:#C8102E"></span>HR ({_sp_nhr})</span>
  <span><span class="dot" style="background:#1A2E47;border:1px solid #2A3E57"></span>Out ({_sp_no})</span>
</div>
<script>
var cv=document.getElementById('sc'),ctx=cv.getContext('2d');
var W=cv.width,H=cv.height,SX=W/250,SY=H/260;
function px(x){{return x*SX;}} function py(y){{return y*SY;}}
ctx.fillStyle='{CARD_BG}';ctx.fillRect(0,0,W,H);
ctx.beginPath();ctx.moveTo(px(6),py(40));
ctx.quadraticCurveTo(px(125),py(0),px(244),py(40));
ctx.strokeStyle='#C8102E';ctx.lineWidth=2;ctx.stroke();
ctx.beginPath();
ctx.moveTo(px(125),py(208));ctx.lineTo(px(6),py(40));
ctx.moveTo(px(125),py(208));ctx.lineTo(px(244),py(40));
ctx.strokeStyle='#FFFFFF44';ctx.lineWidth=1.5;ctx.stroke();
ctx.beginPath();ctx.arc(px(125),py(152),px(46),0,Math.PI*2);
ctx.strokeStyle='#C8A06033';ctx.lineWidth=1;ctx.stroke();
var hm=[px(125),py(208)],b1=[px(172),py(161)],b2=[px(125),py(112)],b3=[px(78),py(161)];
ctx.beginPath();
ctx.moveTo(hm[0],hm[1]);ctx.lineTo(b1[0],b1[1]);ctx.lineTo(b2[0],b2[1]);
ctx.lineTo(b3[0],b3[1]);ctx.closePath();
ctx.strokeStyle='#FFFFFF55';ctx.lineWidth=1.5;ctx.stroke();
[b1,b2,b3].forEach(function(b){{ctx.fillStyle='#FFFFFF88';ctx.fillRect(b[0]-4,b[1]-4,8,8);}});
ctx.beginPath();ctx.arc(px(125),py(158),px(4),0,Math.PI*2);ctx.fillStyle='#C8A06055';ctx.fill();
ctx.beginPath();ctx.arc(px(125),py(208),px(3),0,Math.PI*2);ctx.fillStyle='#FFFFFF77';ctx.fill();
var hits={_sp_js};
hits.forEach(function(h){{
  ctx.globalAlpha=0.82;ctx.beginPath();ctx.arc(px(h.x),py(h.y),4,0,Math.PI*2);
  ctx.fillStyle=h.c;ctx.fill();ctx.globalAlpha=1;
  ctx.beginPath();ctx.arc(px(h.x),py(h.y),4,0,Math.PI*2);
  ctx.strokeStyle='rgba(0,0,0,0.25)';ctx.lineWidth=0.5;ctx.stroke();
}});
</script></body></html>"""
            _spc1, _spc2 = st.columns([2, 1])
            with _spc1:
                components.html(_sp_html, height=420)
            with _spc2:
                _lf2 = _sp_in[_sp_in["hc_x"] < 100]
                _cf2 = _sp_in[(_sp_in["hc_x"] >= 100) & (_sp_in["hc_x"] <= 150)]
                _rf2 = _sp_in[_sp_in["hc_x"] > 150]
                _dt2 = max(len(_sp_in), 1)
                _dh2 = ('<div style="margin-top:20px">'
                        '<div style="font-size:.6rem;font-weight:700;color:#C8102E;'
                        'letter-spacing:2px;text-transform:uppercase;margin-bottom:12px">'
                        'Spray Direction</div>')
                for _dl2, _dd2 in [("Left Field",_lf2),("Center",_cf2),("Right Field",_rf2)]:
                    _dp2 = round(len(_dd2)/_dt2*100)
                    _dh2 += (f'<div style="margin-bottom:9px">'
                             f'<div style="display:flex;justify-content:space-between;'
                             f'font-size:.74rem;color:#8B9EC4;margin-bottom:3px">'
                             f'<span>{_dl2}</span><span style="color:#F4F8FF">{_dp2}%</span></div>'
                             f'<div style="background:#0A1525;border-radius:3px;height:5px">'
                             f'<div style="width:{_dp2}%;background:#00BFFF;height:5px;'
                             f'border-radius:3px"></div></div></div>')
                _dh2 += ('<div style="margin-top:14px;font-size:.6rem;font-weight:700;'
                         'color:#C8102E;letter-spacing:2px;text-transform:uppercase;'
                         'margin-bottom:10px">Hit Breakdown</div>')
                for _et2, _ec2, _el2 in [("home_run","#C8102E","HR"),("triple","#FFD700","3B"),
                                          ("double","#FFA726","2B"),("single","#00BFFF","1B")]:
                    _ecnt2 = len(_sp_in[_sp_in["events"]==_et2])
                    if _ecnt2 == 0: continue
                    _dh2 += (f'<div style="display:flex;align-items:center;gap:8px;margin-bottom:6px">'
                             f'<div style="width:9px;height:9px;border-radius:50%;'
                             f'background:{_ec2};flex-shrink:0"></div>'
                             f'<span style="color:#8B9EC4;font-size:.74rem;width:28px">{_el2}</span>'
                             f'<span style="color:#F4F8FF;font-weight:700;font-size:.85rem">'
                             f'{_ecnt2}</span></div>')
                _dh2 += '</div>'
                st.markdown(_dh2, unsafe_allow_html=True)

    # ── Swing Profile — Bat Angle (Hitters — 2024+ Statcast) ─────────────────────
    if mode == "Hitters":
        st.markdown('<div class="section-header">Swing Profile — Bat Angle</div>', unsafe_allow_html=True)
        _ba_has_data = (not _sr_sc_raw.empty and "attack_angle" in _sr_sc_raw.columns
                        and _sr_sc_raw["attack_angle"].notna().any())
        if _ba_has_data:
            _ba_raw = _sr_sc_raw[_sr_sc_raw["attack_angle"].notna()].copy()
            if "pitch_type" in _ba_raw.columns:
                _ba_raw = _ba_raw[_ba_raw["pitch_type"].notna() & (_ba_raw["pitch_type"].str.strip() != "")]
        else:
            _ba_raw = pd.DataFrame()
        if not _ba_raw.empty:
            _PT_CLR_B = ["#C8102E","#00BFFF","#C4A962","#2ecc71","#8B9EC4","#FFA726","#EF5350","#FF69B4"]
            _ba_overall = round(float(_ba_raw["attack_angle"].mean()), 1)
            _ba_agg = (_ba_raw.groupby("pitch_type")
                       .agg(n=("attack_angle","count"), ba=("attack_angle","mean"))
                       .reset_index())
            _ba_agg = _ba_agg[_ba_agg["n"] >= 10].copy()
            _ba_agg["pname"] = _ba_agg["pitch_type"].map(PITCH_NAMES).fillna(_ba_agg["pitch_type"])
            _ba_c1, _ba_c2 = st.columns([2, 3])
            with _ba_c1:
                # ── Bat-angle illustration (mirrored by handedness) ──────────────────
                #   Knob/handle rise ABOVE the level line; barrel + ball dip BELOW it.
                _stand = "R"
                if "stand" in _ba_raw.columns:
                    _sv = _ba_raw["stand"].dropna()
                    if not _sv.empty: _stand = _sv.mode()[0]
                _dir = 1.0 if _stand == "L" else -1.0      # RHB barrel→lower-left, LHB mirrored
                _hand_txt = ("Left-Handed Batter" if _stand == "L"
                             else "Right-Handed Batter" if _stand == "R" else "Switch Hitter")
                _rad = math.radians(_ba_overall)
                _Vx, _Vy = 150.0 + _dir * 34, 108.0       # contact point, on the level line
                _HL, _BL, _r = 132.0, 58.0, 42.0
                # unit vectors: handle goes up-and-back (toward body); barrel goes down-and-out
                _kux, _kuy = -_dir * math.cos(_rad), -math.sin(_rad)   # toward knob (above line)
                _bux, _buy =  _dir * math.cos(_rad),  math.sin(_rad)   # toward barrel (below line)
                _Kx, _Ky = _Vx + _kux * _HL, _Vy + _kuy * _HL          # knob (top)
                _Bx, _By = _Vx + _bux * _BL, _Vy + _buy * _BL          # barrel tip (bottom)
                _Px, _Py = _Vx + _kux * _HL * 0.26, _Vy + _kuy * _HL * 0.26  # barrel→handle junction
                _ballx, _bally = (_Bx + _Px) / 2, (_By + _Py) / 2   # halfway up the barrel
                # angle arc (sampled, between the level line and the handle) — no sweep ambiguity
                _apts = []
                for _i in range(13):
                    _phi = _rad * _i / 12.0
                    _apts.append((_Vx - _dir * math.cos(_phi) * _r, _Vy - math.sin(_phi) * _r))
                _arc = "M " + " L ".join(f"{x:.1f} {y:.1f}" for x, y in _apts)
                _llx = 20.0 if _dir > 0 else 280.0
                _lvl_anchor = "start" if _dir > 0 else "end"
                _svg = (
                    f'<svg viewBox="0 0 300 200" width="100%" style="max-height:190px;display:block;margin:auto">'
                    f'<line x1="16" y1="{_Vy:.0f}" x2="284" y2="{_Vy:.0f}" stroke="#8B9EC4" stroke-width="1.3" stroke-dasharray="5 4"/>'
                    f'<text x="{_llx:.0f}" y="{_Vy+14:.0f}" fill="#8B9EC4" font-size="9" text-anchor="{_lvl_anchor}">level (0°)</text>'
                    f'<path d="{_arc}" fill="none" stroke="#C8102E" stroke-width="1.8"/>'
                    f'<line x1="{_Bx:.1f}" y1="{_By:.1f}" x2="{_Px:.1f}" y2="{_Py:.1f}" stroke="#E8C97A" stroke-width="11" stroke-linecap="round"/>'
                    f'<line x1="{_Px:.1f}" y1="{_Py:.1f}" x2="{_Kx:.1f}" y2="{_Ky:.1f}" stroke="#9A7B3F" stroke-width="5" stroke-linecap="round"/>'
                    f'<circle cx="{_Kx:.1f}" cy="{_Ky:.1f}" r="5" fill="#9A7B3F"/>'
                    f'<circle cx="{_ballx:.1f}" cy="{_bally:.1f}" r="6" fill="#F4F8FF"/>'
                    f'<text x="{_Vx - _dir*40:.1f}" y="{_Vy+26:.0f}" fill="#C8102E" font-size="17" font-weight="800" text-anchor="middle">{_ba_overall}°</text>'
                    f'</svg>'
                )
                st.markdown(
                    f'<div style="background:#0F1E32;border:1px solid #1A2E47;border-radius:12px;'
                    f'padding:18px 16px 14px;margin-top:8px">'
                    f'<div style="font-size:.62rem;color:#C8102E;font-weight:700;letter-spacing:2px;'
                    f'text-transform:uppercase;text-align:center;margin-bottom:6px">Average Bat Angle</div>'
                    f'{_svg}'
                    f'<div style="font-size:.74rem;color:#8B9EC4;text-align:center;margin-top:4px">'
                    f'attack angle at contact · {_hand_txt}</div>'
                    f'</div>',
                    unsafe_allow_html=True
                )
            with _ba_c2:
                _bas = _ba_agg.sort_values("ba", ascending=True).reset_index(drop=True)
                ech({
                    **_base("Avg Bat Angle by Pitch Type (°)"),
                    "legend":{"show":False},
                    "grid":{"left":"30%","right":"16%","top":"14%","bottom":"8%"},
                    "xAxis":{"type":"value","axisLabel":{"color":SUBTEXT,"fontSize":9,"formatter":"{value}°"},
                             "splitLine":{"lineStyle":{"color":LINE_CLR}},
                             "axisLine":{"lineStyle":{"color":LINE_CLR}}},
                    "yAxis":{"type":"category","data":_bas["pname"].tolist(),
                             "axisLabel":{"color":TEXT,"fontSize":10},
                             "axisLine":{"lineStyle":{"color":LINE_CLR}}},
                    "series":[{"type":"bar","barMaxWidth":26,
                               "data":[{"value":round(float(_bas.iloc[_bi]["ba"]),1),
                                        "itemStyle":{"color":_PT_CLR_B[_bi%len(_PT_CLR_B)],"borderRadius":[0,4,4,0]},
                                        "label":{"show":True,"position":"right","color":TEXT,"fontSize":9,
                                                 "formatter":f"{round(float(_bas.iloc[_bi]['ba']),1)}°"}}
                                       for _bi in range(len(_bas))]}],
                }, height=300)
        else:
            st.markdown(
                '<div style="background:#0F1E32;border:1px solid #1A2E47;border-radius:10px;'
                'padding:18px;color:#8B9EC4;font-size:.85rem;text-align:center;margin-bottom:16px">'
                'Bat angle (attack angle) data is available for 2024+ seasons. Select 2024 or later to view.</div>',
                unsafe_allow_html=True
            )

    # ── Tool Grades + OFP ────────────────────────────────────────────────────────
    if grades:
        _tg_col, _ofp_col = st.columns([5, 2])
        with _tg_col:
            st.markdown(
                f'<div style="font-size:.62rem;font-weight:700;color:#C8102E;'
                f'letter-spacing:2.5px;text-transform:uppercase;margin-bottom:10px">'
                f'Tool Grades · 20-80 Scouting Scale</div>',
                unsafe_allow_html=True
            )
            _bars_html = "".join(_grade_bar(t, v) for t, v in grades.items())
            st.markdown(
                f'<div style="background:#0F1E32;border-radius:12px;padding:16px 22px;'
                f'border:1px solid #1A2E47">{_bars_html}</div>',
                unsafe_allow_html=True
            )
        with _ofp_col:
            _role_str = _ofp_role(ofp, grades)
            st.markdown(
                f'<div style="background:#0F1E32;border-radius:12px;padding:28px 20px;'
                f'border:1px solid #1A2E47;display:flex;flex-direction:column;'
                f'align-items:center;text-align:center;height:100%;box-sizing:border-box">'
                f'<div style="font-size:.62rem;font-weight:700;color:#C8102E;'
                f'letter-spacing:2.5px;text-transform:uppercase;margin-bottom:14px">OFP</div>'
                f'<div style="font-size:5rem;font-weight:900;font-family:monospace;'
                f'color:{ofp_c};line-height:1">{ofp}</div>'
                f'<div style="font-size:.75rem;font-weight:700;color:{ofp_c};'
                f'text-transform:uppercase;letter-spacing:1px;margin-top:8px">'
                f'{grade_label(ofp)}</div>'
                f'<div style="margin-top:14px;padding-top:14px;border-top:1px solid #1A2E47;'
                f'width:100%">'
                f'<div style="font-size:.72rem;color:#8B9EC4;line-height:1.5">{_role_str}</div>'
                f'</div></div>',
                unsafe_allow_html=True
            )

    # ── Pitch Arsenal (Pitchers only) ────────────────────────────────────────────
    if mode == "Pitchers" and mid and HAS_PB:
        _sc_raw = pd.DataFrame()
        for _s in sorted(sel_seasons, reverse=True):
            _tmp = get_statcast_pitcher_raw(mid, _s)
            if not _tmp.empty:
                _sc_raw = _tmp
                break
        if not _sc_raw.empty:
            _arsenal = build_arsenal(_sc_raw)
            if not _arsenal.empty:
                st.markdown(
                    '<div class="section-header">Pitch Arsenal</div>',
                    unsafe_allow_html=True
                )
                _arc1, _arc2 = st.columns([1, 2])
                with _arc1:
                    _pie_colors = ["#C8102E","#00BFFF","#C4A962","#2ecc71","#8B9EC4","#FFA726","#EF5350"]
                    _pie_data   = [
                        {"value": float(r["Usage%"]), "name": r["Pitch"]}
                        for _, r in _arsenal.iterrows()
                    ]
                    ech({
                        **_base("Pitch Usage"),
                        "legend": {"bottom": 0, "textStyle": {"color": TEXT, "fontSize": 10}},
                        "series": [{
                            "name": "Usage",
                            "type": "pie",
                            "radius": ["44%", "72%"],
                            "center": ["50%", "44%"],
                            "data": _pie_data,
                            "label": {
                                "show": True, "color": TEXT, "fontSize": 10,
                                "formatter": "{b}\n{d}%",
                            },
                            "itemStyle": {"borderColor": CARD_BG, "borderWidth": 2},
                            "color": _pie_colors,
                        }],
                    }, height=310)
                with _arc2:
                    _a_heads = ["Pitch", "Usage %", "Velo", "Spin", "xwOBA", "EV"]
                    _a_rows  = []
                    for _, _ar in _arsenal.iterrows():
                        _a_rows.append([
                            _ar.get("Pitch", ""),
                            f'{_ar.get("Usage%", 0):.1f}%',
                            f'{_ar.get("Velo", 0):.1f}',
                            f'{int(_ar.get("Spin", 0)):,}',
                            f'{_ar.get("xwOBA", 0):.3f}',
                            f'{_ar.get("EV", 0):.1f}',
                        ])
                    st.markdown(_stat_table_html(_a_rows, _a_heads), unsafe_allow_html=True)

    # ── Pitch Movement + Arm Slot (Pitchers only) ────────────────────────────────
    if mode == "Pitchers":
        st.markdown('<div class="section-header">Pitch Movement & Arm Slot</div>', unsafe_allow_html=True)
        _mov_need = ["pitch_type", "pfx_x", "pfx_z"]
        _mov_has_data = (not _sr_sc_raw.empty and
                         all(c in _sr_sc_raw.columns for c in _mov_need))
        if _mov_has_data:
            _mov_raw = _sr_sc_raw[
                _mov_need + [c for c in ["release_pos_x","release_pos_z","p_throws"]
                             if c in _sr_sc_raw.columns]
            ].dropna(subset=_mov_need).copy()
            _mov_raw = _mov_raw[_mov_raw["pitch_type"].str.strip() != ""]
        else:
            _mov_raw = pd.DataFrame()
        if not _mov_raw.empty:
                _PT_CLR = ["#C8102E","#00BFFF","#C4A962","#2ecc71","#8B9EC4","#FFA726","#EF5350","#FF69B4"]
                _mov_raw = _mov_raw.copy()
                # pitcher's POV — flip horizontal break (pfx_x is catcher's view)
                _mov_raw["hbreak"] = _mov_raw["pfx_x"] * -12
                _mov_raw["vbreak"] = _mov_raw["pfx_z"] * 12
                _mov_agg = (_mov_raw.groupby("pitch_type")
                            .agg(hbreak=("hbreak","mean"), vbreak=("vbreak","mean"), n=("pitch_type","count"))
                            .reset_index())
                _mov_agg["pname"] = _mov_agg["pitch_type"].map(PITCH_NAMES).fillna(_mov_agg["pitch_type"])
                _mov_c1, _mov_c2 = st.columns(2)
                with _mov_c1:
                    _mov_series = []
                    for _mi, _mrw in enumerate(_mov_agg.itertuples(index=False)):
                        _mc = _PT_CLR[_mi % len(_PT_CLR)]
                        _msz = max(14, min(48, int(_mrw.n / 15)))
                        _mov_series.append({
                            "name": _mrw.pname,
                            "type": "scatter",
                            "data": [[round(float(_mrw.hbreak),1), round(float(_mrw.vbreak),1)]],
                            "symbolSize": _msz,
                            "itemStyle": {"color": _mc},
                            "label": {"show": True, "position": "top",
                                      "formatter": _mrw.pname, "fontSize": 9, "color": TEXT},
                        })
                    ech({
                        **_base("Ball Movement — pitcher's view (in.)"),
                        "legend": {"show": False},
                        "grid": {"left":"10%","right":"5%","top":"16%","bottom":"14%"},
                        "xAxis": {
                            "type":"value","name":"Horizontal Break (in.)",
                            "nameTextStyle":{"color":SUBTEXT,"fontSize":9},
                            "nameLocation":"center","nameGap":22,
                            "axisLabel":{"color":SUBTEXT,"fontSize":9},
                            "splitLine":{"lineStyle":{"color":LINE_CLR}},
                            "axisLine":{"lineStyle":{"color":LINE_CLR}},
                        },
                        "yAxis": {
                            "type":"value","name":"Vert. Break (in.)",
                            "nameTextStyle":{"color":SUBTEXT,"fontSize":9},
                            "axisLabel":{"color":SUBTEXT,"fontSize":9},
                            "splitLine":{"lineStyle":{"color":LINE_CLR}},
                            "axisLine":{"lineStyle":{"color":LINE_CLR}},
                        },
                        "series": _mov_series + [{
                            "type":"scatter","data":[],"silent":True,
                            "markLine":{"silent":True,"symbol":"none",
                                        "lineStyle":{"color":SUBTEXT,"type":"dashed","width":1},
                                        "data":[{"xAxis":0},{"yAxis":0}],"label":{"show":False}},
                        }],
                    }, height=330)
                with _mov_c2:
                    if "release_pos_x" in _mov_raw.columns and "release_pos_z" in _mov_raw.columns:
                        _hand = "R"
                        if "p_throws" in _mov_raw.columns and not _mov_raw["p_throws"].dropna().empty:
                            _hand = _mov_raw["p_throws"].dropna().mode()[0]
                        _arm_aggs = {"rx": ("release_pos_x","mean"),
                                     "rz": ("release_pos_z","mean"),
                                     "n":  ("pitch_type","count")}
                        if "arm_angle" in _mov_raw.columns:
                            _arm_aggs["aa"] = ("arm_angle","mean")
                        _arm_grp = _mov_raw.groupby("pitch_type").agg(**_arm_aggs).reset_index()
                        # pitcher's POV — flip horizontal release (release_pos_x is catcher's view)
                        _arm_grp["relx"] = -_arm_grp["rx"]
                        _arm_grp["pname"] = _arm_grp["pitch_type"].map(PITCH_NAMES).fillna(_arm_grp["pitch_type"])
                        # Arm angle drawn as straight lines radiating from the 0° axis (origin)
                        _sign = 1.0 if _hand == "R" else -1.0
                        _L = 6.0
                        _line_series, _end_pts = [], []
                        for _ai, _arw in enumerate(_arm_grp.itertuples(index=False)):
                            _ac = _PT_CLR[_ai % len(_PT_CLR)]
                            _ang = (float(_arw.aa) if "aa" in _arm_grp.columns
                                    else math.degrees(math.atan2(float(_arw.rz), abs(float(_arw.relx)) or 0.01)))
                            _rad = math.radians(_ang)
                            _ux = round(_sign * math.cos(_rad) * _L, 2)
                            _uy = round(math.sin(_rad) * _L, 2)
                            _line_series.append({
                                "name": _arw.pname, "type": "line",
                                "data": [[0, 0], [_ux, _uy]],
                                "symbol": "none", "lineStyle": {"color": _ac, "width": 3}, "z": 2,
                            })
                            _end_pts.append({
                                "value": [_ux, _uy], "itemStyle": {"color": _ac},
                                "label": {"show": True,
                                          "position": "right" if _sign > 0 else "left",
                                          "formatter": f"{_arw.pname}  {round(_ang)}°",
                                          "fontSize": 9, "color": TEXT},
                            })
                        _xaxis = {
                            "type":"value","name":"0° = sidearm  ·  90° = over-the-top",
                            "nameLocation":"center","nameGap":24,
                            "nameTextStyle":{"color":SUBTEXT,"fontSize":9},
                            "axisLabel":{"show":False},"splitLine":{"show":False},
                            "axisTick":{"show":False},
                            "axisLine":{"lineStyle":{"color":SUBTEXT,"width":1.4}},
                        }
                        if _sign > 0: _xaxis["min"] = 0
                        else:         _xaxis["max"] = 0
                        ech({
                            **_base(f"Arm Angle by Pitch ({_hand}HP — pitcher's view)"),
                            "legend": {"show": False},
                            "grid": {"left":"10%","right":"15%","top":"16%","bottom":"16%"},
                            "xAxis": _xaxis,
                            "yAxis": {
                                "type":"value","min":0,
                                "axisLabel":{"show":False},"splitLine":{"show":False},
                                "axisTick":{"show":False},
                                "axisLine":{"lineStyle":{"color":LINE_CLR}},
                            },
                            "series": _line_series + [
                                {"type":"scatter","data":_end_pts,"symbolSize":8,"z":3},
                            ],
                        }, height=330)
        else:
            st.markdown(
                '<div style="background:#0F1E32;border:1px solid #1A2E47;border-radius:10px;'
                'padding:18px;color:#8B9EC4;font-size:.85rem;text-align:center;margin-bottom:16px">'
                'Statcast pitch movement data not available for the selected season.</div>',
                unsafe_allow_html=True
            )

    # ── Season Stats Table ───────────────────────────────────────────────────────
    st.markdown('<div class="section-header">Season Stats</div>', unsafe_allow_html=True)
    if not sn_df.empty:
        if mode == "Hitters":
            _sh = ["Season","Team","G","PA","AVG","OBP","SLG","OPS","HR","RBI","SB","wRC+","WAR"]
            _sr_rows = []
            for _, _rr in sn_df.sort_values("Season", ascending=False).iterrows():
                _sr_rows.append([
                    int(_rr.get("Season", 0)),
                    _rr.get("Team", ""),
                    safe(_rr.get("G"),    "{:.0f}"),
                    safe(_rr.get("PA"),   "{:.0f}"),
                    safe(_rr.get("AVG"),  "{:.3f}"),
                    safe(_rr.get("OBP"),  "{:.3f}"),
                    safe(_rr.get("SLG"),  "{:.3f}"),
                    safe(_rr.get("OPS"),  "{:.3f}"),
                    safe(_rr.get("HR"),   "{:.0f}"),
                    safe(_rr.get("RBI"),  "{:.0f}"),
                    safe(_rr.get("SB"),   "{:.0f}"),
                    safe(_rr.get("wRC+"), "{:.0f}"),
                    safe(_rr.get("WAR"),  "{:.1f}"),
                ])
        else:
            _sh = ["Season","Team","G","GS","IP","ERA","WHIP","K%","BB%","K/9","FIP","WAR"]
            _sr_rows = []
            for _, _rr in sn_df.sort_values("Season", ascending=False).iterrows():
                _sr_rows.append([
                    int(_rr.get("Season", 0)),
                    _rr.get("Team", ""),
                    safe(_rr.get("G"),    "{:.0f}"),
                    safe(_rr.get("GS"),   "{:.0f}"),
                    safe(_rr.get("IP"),   "{:.1f}"),
                    safe(_rr.get("ERA"),  "{:.2f}"),
                    safe(_rr.get("WHIP"), "{:.2f}"),
                    safe(_rr.get("K%"),   "{:.1f}") + "%",
                    safe(_rr.get("BB%"),  "{:.1f}") + "%",
                    safe(_rr.get("K/9"),  "{:.1f}"),
                    safe(_rr.get("FIP"),  "{:.2f}"),
                    safe(_rr.get("WAR"),  "{:.1f}"),
                ])
        st.markdown(_stat_table_html(_sr_rows, _sh), unsafe_allow_html=True)

    # ── Gameplan ─────────────────────────────────────────────────────────────────
    if grades and row is not None:
        _gp_label = "Hitter's Gameplan" if mode == "Pitchers" else "Pitcher's Gameplan"
        st.markdown(f'<div class="section-header">{_gp_label}</div>', unsafe_allow_html=True)
        _bullets = _gameplan_bullets(sr_player, grades, row)
        _bullets_html = "".join(
            f'<div style="display:flex;align-items:flex-start;gap:14px;padding:13px 18px;'
            f'background:#0F1E32;border-radius:9px;border-left:3px solid #C8102E;'
            f'margin-bottom:8px;border:1px solid #1A2E47;border-left-width:3px">'
            f'<div style="width:24px;height:24px;background:#C8102E;border-radius:50%;'
            f'display:flex;align-items:center;justify-content:center;flex-shrink:0;margin-top:1px">'
            f'<span style="color:#fff;font-size:.72rem;font-weight:900">{i+1}</span></div>'
            f'<div style="color:#F4F8FF;font-size:.84rem;line-height:1.6">{b}</div>'
            f'</div>'
            for i, b in enumerate(_bullets)
        )
        st.markdown(_bullets_html, unsafe_allow_html=True)

    # ── Zone Analysis + Pitch Maps (Statcast) ────────────────────────────────────
    _zone_raw    = _sr_sc_raw
    _zone_season = _sr_sc_season
    if not _zone_raw.empty and "plate_x" in _zone_raw.columns:
        _hand_label = ""
        if mode == "Hitters" and "stand" in _zone_raw.columns:
            _st_vals = _zone_raw["stand"].dropna()
            if not _st_vals.empty:
                _hv = _st_vals.mode()[0]
                _hand_label = (" · ◀ Left-Handed Batter" if _hv == "L"
                               else " · Right-Handed Batter ▶" if _hv == "R"
                               else " · Switch Hitter")
        st.markdown(
            f'<div class="section-header">Zone Analysis '
            f'<span style="color:#8B9EC4;font-size:.76rem;font-weight:400">'
            f'({_zone_season} Statcast — catcher\'s view{_hand_label})</span></div>',
            unsafe_allow_html=True
        )
        if True:
            _NX, _NZ = 5, 5
            _XE = np.linspace(-1.0, 1.0, _NX + 1)
            _ZE = np.linspace(1.5, 3.5, _NZ + 1)

            def _bin_sc(df):
                df = df.dropna(subset=["plate_x","plate_z"]).copy()
                df = df[df["plate_x"].between(-1.0, 1.0) & df["plate_z"].between(1.5, 3.5)]
                df["_xi"] = pd.cut(df["plate_x"], bins=_XE, labels=False, include_lowest=True)
                df["_zi"] = pd.cut(df["plate_z"], bins=_ZE, labels=False, include_lowest=True)
                return df.dropna(subset=["_xi","_zi"])

            def _zone_vals(binned, fn, min_n=3):
                out = []
                for xi in range(_NX):
                    for zi in range(_NZ):
                        g = binned[(binned["_xi"]==xi) & (binned["_zi"]==zi)]
                        v = fn(g) if len(g) >= min_n else None
                        if v is not None:
                            out.append([xi, zi, v])
                return out

            def _zone_chart(data, title, vmin, vmax, colors):
                return {
                    "backgroundColor": CARD_BG,
                    "title": {"text": title, "left": "center", "top": 3,
                              "textStyle": {"color": TEXT, "fontSize": 11, "fontWeight": "bold"}},
                    "grid": {"top": "17%", "bottom": "3%", "left": "3%", "right": "3%"},
                    "xAxis": {"type":"category","data":list(range(_NX)),
                              "axisLabel":{"show":False},"axisLine":{"show":False},
                              "axisTick":{"show":False},"splitLine":{"show":False}},
                    "yAxis": {"type":"category","data":list(range(_NZ)),
                              "axisLabel":{"show":False},"axisLine":{"show":False},
                              "axisTick":{"show":False},"splitLine":{"show":False}},
                    "visualMap": {"min":vmin,"max":vmax,"show":False,
                                  "inRange":{"color":colors}},
                    "series": [{"type":"heatmap","data":data,
                                "label":{"show":True,"color":"#FFFFFF",
                                         "fontSize":9,"fontWeight":"bold"},
                                "itemStyle":{"borderWidth":3,"borderColor":CARD_BG}}],
                }

            _SWINGS = {"swinging_strike","swinging_strike_blocked","foul","foul_tip",
                       "hit_into_play","foul_bunt","missed_bunt"}
            _WHIFFS = {"swinging_strike","swinging_strike_blocked"}
            _HITS   = {"single","double","triple","home_run"}
            _AB_EV  = {"single","double","triple","home_run","field_out","strikeout",
                       "grounded_into_double_play","double_play","force_out",
                       "fielders_choice","fielders_choice_out","strikeout_double_play"}

            def _f_density(g): return int(len(g))
            def _f_whiff(g):
                sw = g["description"].isin(_SWINGS).sum()
                wh = g["description"].isin(_WHIFFS).sum()
                return round(wh/sw*100, 1) if sw >= 3 else None
            def _f_ba(g):
                ab = g[g["events"].isin(_AB_EV)]
                if len(ab) < 2: return None
                return round(g["events"].isin(_HITS).sum()/len(ab), 3)
            def _f_xwoba(g):
                x = g["estimated_woba_using_speedangle"].dropna()
                return round(float(x.mean()), 3) if len(x) >= 3 else None

            _binned_all = _bin_sc(_zone_raw)
            _d_dens  = _zone_vals(_binned_all, _f_density, 1)
            _d_whiff = _zone_vals(_binned_all, _f_whiff)
            _d_third = _zone_vals(_binned_all, _f_ba if mode=="Pitchers" else _f_xwoba)

            _zc1, _zc2, _zc3 = st.columns(3)
            with _zc1:
                if _d_dens:
                    _dmax = max(d[2] for d in _d_dens)
                    ech(_zone_chart(_d_dens,"Pitch Density",0,_dmax,[CARD_BG,"#C8102E"]),height=240)
            with _zc2:
                if _d_whiff:
                    ech(_zone_chart(_d_whiff,"Whiff Rate %",0,50,
                        [CARD_BG,"#C8102E"] if mode=="Pitchers" else [CARD_BG,"#00BFFF"]),height=240)
                else:
                    st.caption("Not enough swing data for whiff map.")
            with _zc3:
                if _d_third:
                    _t3_title = "BA Against" if mode=="Pitchers" else "xwOBA by Zone"
                    _t3_clrs  = [CARD_BG,"#C8102E"] if mode=="Pitchers" else [CARD_BG,"#00C851"]
                    _t3_mm    = (0.0, 0.4) if mode=="Pitchers" else (0.2, 0.6)
                    ech(_zone_chart(_d_third,_t3_title,*_t3_mm,_t3_clrs),height=240)
                else:
                    st.caption("Not enough in-play data for zone map.")

            # Whiff rate and xwOBA by pitch type (pitchers) — extra pair of maps
            if mode == "Pitchers":
                _pt_all = (_zone_raw[_zone_raw["pitch_type"].notna()]["pitch_type"]
                           .value_counts())
                _pt_show = _pt_all[_pt_all >= 20].index.tolist()

                if _pt_show:
                    st.markdown('<div class="section-header">Pitch Location by Type</div>',
                                unsafe_allow_html=True)
                    _pt_palette = ["#C8102E","#00BFFF","#C4A962","#2ecc71",
                                   "#FFA726","#EF5350","#8B9EC4","#B0C4DE"]
                    for _row_start in range(0, min(len(_pt_show), 8), 4):
                        _row_types = _pt_show[_row_start:_row_start+4]
                        _ptcols = st.columns(len(_row_types))
                        for _pti, _pt in enumerate(_row_types):
                            _pt_df = _zone_raw[_zone_raw["pitch_type"] == _pt]
                            _pt_b  = _bin_sc(_pt_df)
                            _pt_d  = _zone_vals(_pt_b, _f_density, 1)
                            _pt_nm = PITCH_NAMES.get(_pt, _pt)
                            _pt_c  = _pt_palette[(_row_start+_pti) % len(_pt_palette)]
                            if _pt_d:
                                _pt_mx = max(v[2] for v in _pt_d)
                                with _ptcols[_pti]:
                                    ech(_zone_chart(
                                        _pt_d,
                                        f"{_pt_nm}  ({int(_pt_df.shape[0])})",
                                        0, _pt_mx, [CARD_BG, _pt_c]
                                    ), height=220)

                # Per-pitch-type whiff rate + BA heatmaps
                st.markdown('<div class="section-header">Whiff Rate · BA Against by Pitch Type</div>',
                            unsafe_allow_html=True)
                for _row_start in range(0, min(len(_pt_show), 8), 4):
                    _row_types = _pt_show[_row_start:_row_start+4]
                    _wcols = st.columns(len(_row_types))
                    for _pti, _pt in enumerate(_row_types):
                        _pt_df = _zone_raw[_zone_raw["pitch_type"] == _pt]
                        _pt_b  = _bin_sc(_pt_df)
                        _dw = _zone_vals(_pt_b, _f_whiff)
                        _db = _zone_vals(_pt_b, _f_ba)
                        _pt_nm = PITCH_NAMES.get(_pt, _pt)
                        with _wcols[_pti]:
                            if _dw:
                                ech(_zone_chart(_dw,f"{_pt_nm} Whiff%",0,60,[CARD_BG,"#C8102E"]),height=200)
                            if _db:
                                ech(_zone_chart(_db,f"{_pt_nm} BA",0.0,0.4,[CARD_BG,"#FFA726"]),height=200)

    st.stop()

# ── Controls (top of page, no sidebar needed) ──────────────────────────────────
st.markdown('<div class="section-header">Select Players</div>', unsafe_allow_html=True)
ctrl1, _ = st.columns([1, 3])
with ctrl1:
    mode = st.radio("Compare", ["Hitters","Pitchers"], horizontal=True)
sel_seasons = st.pills("Seasons", ALL_SEASONS, default=ALL_SEASONS, selection_mode="multi")
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

# (p_seasons, p_latest, p_mlbam, safe defined above before scouting report)

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
    _aw_raw = get_player_awards(mlbam)
    _aw_map = {
        "ALMVP":("MVP","#C4A962"),"NLMVP":("MVP","#C4A962"),
        "ALCY":("Cy Young","#00BFFF"),"NLCY":("Cy Young","#00BFFF"),
        "ALGG":("Gold Glove","#2ecc71"),"NLGG":("Gold Glove","#2ecc71"),
        "ALSS":("Silver Slugger","#B0C4DE"),"NLSS":("Silver Slugger","#B0C4DE"),
        "ALROY":("Rookie of Year","#FFA726"),"NLROY":("Rookie of Year","#FFA726"),
        "ALMVP_RT":("MVP","#C4A962"),"NLMVP_RT":("MVP","#C4A962"),
    }
    _aw_counts = {}
    for _aw in _aw_raw:
        _aid = _aw.get("id","")
        if _aid in _aw_map:
            _al, _ac = _aw_map[_aid]
            _aw_counts[_al] = (_aw_counts.get(_al,(0,_ac))[0]+1, _ac)
    _awards_html = '<div style="display:flex;flex-wrap:wrap;justify-content:center;gap:5px;margin-top:10px">'
    if _aw_counts:
        for _al, (_acnt, _ac) in _aw_counts.items():
            _px = f"{_acnt}x " if _acnt > 1 else ""
            _awards_html += (f'<div style="background:rgba(0,0,0,0.35);border:1px solid {_ac};'
                             f'border-radius:12px;padding:3px 10px;font-size:.63rem;font-weight:700;'
                             f'color:{_ac};white-space:nowrap">{_px}{_al}</div>')
    else:
        _awards_html += ('<div style="font-size:.6rem;color:#8B9EC4;font-style:italic;'
                         'padding:4px 0">No major awards</div>')
    _awards_html += '</div>'
    with col_w:
        st.markdown(f"""
        <div class="player-card" style="border-top-color:{color}">
          {img_tag}
          <div class="player-name">{player}</div>
          <div class="player-team">{team}</div>
          {_awards_html}
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


# (_compute_scouting_grades defined above before scouting report section)


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

    # (Scouting Report moved to dedicated nav page)

# ── Footer ─────────────────────────────────────────────────────────────────────
st.markdown('<div class="divider"></div>', unsafe_allow_html=True)
st.markdown("""
<div style="text-align:center;color:#9BA3B8;font-size:.78rem;padding:6px 0 14px">
  Data: FanGraphs &nbsp;·&nbsp; Baseball Savant (Statcast) &nbsp;·&nbsp; MLB Stats API
  &nbsp;·&nbsp; pybaseball 2.2.7 &nbsp;&nbsp;|&nbsp;&nbsp;
  Built by Sean Bosworth &nbsp;·&nbsp; June 2026
</div>""", unsafe_allow_html=True)
