"""
generate_2026_projections.py  —  Phase 6: live rest-of-season projections.

Pulls 2026 stats through a cutoff date (default: today), builds the same feature
set the models were trained on, and runs the saved Ridge models to project each
qualified player's REST-OF-SEASON wOBA (hitters) / FIP (pitchers). Also includes
the Marcel baseline and current pace for context.

Outputs (to output/):
    ros_projections_2026_hitters.csv
    ros_projections_2026_pitchers.csv

Usage:
    py generate_2026_projections.py                # cutoff = today
    py generate_2026_projections.py 2026-06-30     # explicit cutoff
"""

import sys
from datetime import date
from pathlib import Path
import pandas as pd
import joblib

import pull_projection_data as P
from add_player_age import fetch_birthdates, seasonal_age
from train_projection_models import marcel_hitters, marcel_pitchers, HIT_FEATS, PIT_FEATS

SEASON = 2026
PRIOR  = 2025
OUT = Path(__file__).resolve().parent / "output"
MIN_PRE_PA, MIN_PRE_IP = 80, 20.0


def resolve_cutoff():
    if len(sys.argv) > 1:
        return sys.argv[1]
    t = date.today()
    if t.year != SEASON:                      # clock not in-season -> use a sane default
        return f"{SEASON}-06-30"
    return t.isoformat()


def cutoff_ord(cut):
    d = date.fromisoformat(cut)
    if (d.month, d.day) <= (5, 31): return 0
    if (d.month, d.day) <= (6, 30): return 1
    return 2


def team_map(season):
    """{mlbam: team} from 2026 season standard endpoints (for display)."""
    tm = {}
    for grp in ("hitting", "pitching"):
        url = (f"https://statsapi.mlb.com/api/v1/stats?stats=season&group={grp}"
               f"&season={season}&sportId=1&gameType=R&limit=5000&playerPool=All")
        for sp in P._get(url).get("stats", [{}])[0].get("splits", []):
            pid = (sp.get("player") or {}).get("id")
            t = (sp.get("team") or {}).get("name", "")
            if pid and t:
                tm[pid] = t
    return tm


def main():
    cut = resolve_cutoff()
    cord = cutoff_ord(cut)
    print(f"Projecting rest-of-{SEASON} as of cutoff {cut} (cutoff_ord={cord})")

    # 2026 league context + pre-cutoff data
    fip_const, lg_era, _ = P.league_fip_constant(SEASON)
    pre_h = P.fetch_range(SEASON, "hitting",  P.SEASON_LO.format(SEASON), cut)
    pre_p = P.fetch_range(SEASON, "pitching", P.SEASON_LO.format(SEASON), cut)
    lg_woba = P.league_woba(pre_h)
    print(f"  2026 league to date: wOBA={lg_woba}  ERA={lg_era}  FIPconst={fip_const}")

    # 2025 prior-season baselines
    fc25, _, pit25 = P.league_fip_constant(PRIOR)
    hit25 = P.fetch_range(PRIOR, "hitting", P.SEASON_LO.format(PRIOR), P.SEASON_HI.format(PRIOR))
    prior_hm = {pid: P.hitter_metrics(s) for pid, s in hit25.items()}
    prior_pm = {pid: P.pitcher_metrics(s, fc25) for pid, s in pit25.items()}

    # ages + teams
    ids = set(pre_h) | set(pre_p)
    bd = fetch_birthdates(ids)
    ages = {pid: seasonal_age(bd.get(pid), SEASON) for pid in ids}
    teams = team_map(SEASON)

    # ── Hitters ──────────────────────────────────────────────────────────────
    hrows = []
    for pid, s in pre_h.items():
        m = P.hitter_metrics(s)
        if not m or m["wOBA"] is None or m["PA"] < MIN_PRE_PA:
            continue
        pr = prior_hm.get(pid)
        hrows.append({
            "mlbam": pid, "name": s.get("_name", ""), "team": teams.get(pid, ""),
            "season": SEASON, "cutoff_ord": cord, "age": ages.get(pid),
            "pre_PA": m["PA"], "pre_wOBA": round(m["wOBA"], 4),
            "pre_AVG": _r(m["AVG"]), "pre_OBP": _r(m["OBP"]), "pre_ISO": _r(m["ISO"]),
            "pre_K%": _r(m["K%"], 2), "pre_BB%": _r(m["BB%"], 2), "pre_HR_rate": _r(m["HR_rate"], 2),
            "prior_wOBA": _r(pr["wOBA"], 4) if pr and pr["wOBA"] else None,
            "prior_PA": pr["PA"] if pr else None,
        })
    hdf = pd.DataFrame(hrows)

    # ── Pitchers ─────────────────────────────────────────────────────────────
    prows = []
    for pid, s in pre_p.items():
        m = P.pitcher_metrics(s, fip_const)
        if not m or m["IP"] < MIN_PRE_IP:
            continue
        pr = prior_pm.get(pid)
        prows.append({
            "mlbam": pid, "name": s.get("_name", ""), "team": teams.get(pid, ""),
            "season": SEASON, "cutoff_ord": cord, "age": ages.get(pid),
            "pre_IP": m["IP"], "pre_FIP": round(m["FIP"], 3), "pre_ERA": _r(m["ERA"], 2),
            "pre_K%": _r(m["K%"], 2), "pre_BB%": _r(m["BB%"], 2), "pre_HR9": _r(m["HR9"], 2),
            "prior_FIP": _r(pr["FIP"], 3) if pr and pr["FIP"] else None,
            "prior_IP": pr["IP"] if pr else None,
        })
    pdf = pd.DataFrame(prows)

    # ── Predict ──────────────────────────────────────────────────────────────
    hm = joblib.load(OUT / "proj_model_hitters.joblib")
    pm = joblib.load(OUT / "proj_model_pitchers.joblib")

    hdf["proj_wOBA"]   = hm["model"].predict(hdf[hm["feats"]]).round(4)
    hdf["marcel_wOBA"] = marcel_hitters(hdf, {SEASON: lg_woba}).round(4)
    hdf["model"] = hm["type"]
    hdf = hdf.sort_values("proj_wOBA", ascending=False).reset_index(drop=True)

    pdf["proj_FIP"]   = pm["model"].predict(pdf[pm["feats"]]).round(3)
    pdf["marcel_FIP"] = marcel_pitchers(pdf, {SEASON: lg_era}).round(3)
    pdf["model"] = pm["type"]
    pdf = pdf.sort_values("proj_FIP", ascending=True).reset_index(drop=True)

    hcols = ["name","team","age","pre_PA","pre_wOBA","prior_wOBA","marcel_wOBA","proj_wOBA","model","mlbam"]
    pcols = ["name","team","age","pre_IP","pre_FIP","prior_FIP","marcel_FIP","proj_FIP","model","mlbam"]
    hdf[hcols].to_csv(OUT / "ros_projections_2026_hitters.csv", index=False)
    pdf[pcols].to_csv(OUT / "ros_projections_2026_pitchers.csv", index=False)

    print(f"\n  hitters projected: {len(hdf)}   pitchers projected: {len(pdf)}")
    print("\n  Top 8 hitters by projected ROS wOBA:")
    print(hdf[["name","team","pre_wOBA","proj_wOBA"]].head(8).to_string(index=False))
    print("\n  Top 8 pitchers by projected ROS FIP:")
    print(pdf[["name","team","pre_FIP","proj_FIP"]].head(8).to_string(index=False))
    print("\n  Saved: ros_projections_2026_hitters.csv, ros_projections_2026_pitchers.csv")


def _r(v, n=3):
    return round(v, n) if v is not None else None


if __name__ == "__main__":
    main()
