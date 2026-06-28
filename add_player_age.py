"""
add_player_age.py  —  Phase 2 (feature): add seasonal age to the training tables.

Seasonal age follows the standard baseball convention: a player's age as of
July 1 of that season (matches FanGraphs / Baseball-Reference).

Reads/writes:
    output/proj_train_hitters.csv
    output/proj_train_pitchers.csv   (adds an `age` column in place)
"""

import time
from datetime import date
from pathlib import Path
import requests
import pandas as pd

HEADERS = {"User-Agent": "Mozilla/5.0 (BosworthAnalytics ROS model)"}
OUT = Path(__file__).resolve().parent / "output"
FILES = ["proj_train_hitters.csv", "proj_train_pitchers.csv"]


def fetch_birthdates(ids):
    """Return {mlbam: 'YYYY-MM-DD'} via batched /people?personIds= calls."""
    bd = {}
    ids = list(ids)
    for i in range(0, len(ids), 150):
        chunk = ids[i:i+150]
        url = ("https://statsapi.mlb.com/api/v1/people?personIds="
               + ",".join(str(x) for x in chunk))
        try:
            ppl = requests.get(url, headers=HEADERS, timeout=30).json().get("people", [])
            for p in ppl:
                if p.get("birthDate"):
                    bd[p["id"]] = p["birthDate"]
        except Exception as e:
            print(f"  ! batch {i//150} failed: {e}")
        time.sleep(0.3)
    return bd


def seasonal_age(birth_str, season):
    """Age as of July 1 of the season."""
    try:
        b = date.fromisoformat(birth_str)
    except Exception:
        return None
    ref = date(int(season), 7, 1)
    return ref.year - b.year - ((ref.month, ref.day) < (b.month, b.day))


def main():
    dfs = {f: pd.read_csv(OUT / f) for f in FILES if (OUT / f).exists()}
    if not dfs:
        print("No training CSVs found — run pull_projection_data.py first.")
        return

    all_ids = set()
    for df in dfs.values():
        all_ids |= set(int(x) for x in df["mlbam"].dropna().unique())
    print(f"Fetching birthdates for {len(all_ids)} unique players...")
    bd = fetch_birthdates(all_ids)
    print(f"  got {len(bd)} birthdates")

    for f, df in dfs.items():
        df["age"] = [seasonal_age(bd.get(int(m)), s) if pd.notna(m) else None
                     for m, s in zip(df["mlbam"], df["season"])]
        # place `age` right after `cutoff` for readability
        cols = list(df.columns)
        cols.insert(cols.index("cutoff") + 1, cols.pop(cols.index("age")))
        df = df[cols]
        df.to_csv(OUT / f, index=False)
        miss = df["age"].isna().sum()
        print(f"  {f}: age added (missing {miss}/{len(df)}), "
              f"range {df['age'].min():.0f}-{df['age'].max():.0f}, "
              f"mean {df['age'].mean():.1f}")


if __name__ == "__main__":
    main()
