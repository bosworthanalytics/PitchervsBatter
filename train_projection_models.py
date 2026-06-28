"""
train_projection_models.py  —  Phases 3-5 of the ROS projection model.

For hitters (target = rest-of-season wOBA) and pitchers (target = ROS FIP):
  1. Naive       — "ROS = current pre-cutoff stat" (the do-nothing benchmark)
  2. Marcel      — weighted prior + current, regressed to league mean, age-adjusted
  3. Ridge       — regularized linear regression
  4. GradBoost   — HistGradientBoostingRegressor (the ML model)

Validation is an honest TEMPORAL holdout: train on 2021-2024, test on 2025
(never a random split — that would leak the future). Reports RMSE / MAE / R per
model so we can show ML beats the baseline, plus permutation feature importance.

Artifacts written to output/:
    proj_model_metrics.json
    proj_feature_importance.csv
    proj_model_hitters.joblib  /  proj_model_pitchers.joblib   (trained on all data)
"""

import json
from pathlib import Path
import numpy as np
import pandas as pd
import joblib
from sklearn.linear_model import Ridge
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.pipeline import Pipeline
from sklearn.impute import SimpleImputer
from sklearn.preprocessing import StandardScaler
from sklearn.inspection import permutation_importance
from sklearn.metrics import mean_squared_error, mean_absolute_error, r2_score

OUT = Path(__file__).resolve().parent / "output"
HOLDOUT_SEASON = 2025
CUTOFF_ORD = {"0531": 0, "0630": 1, "0731": 2, 531: 0, 630: 1, 731: 2}

HIT_FEATS = ["cutoff_ord","age","pre_PA","pre_wOBA","pre_AVG","pre_OBP","pre_ISO",
             "pre_K%","pre_BB%","pre_HR_rate","prior_wOBA","prior_PA"]
PIT_FEATS = ["cutoff_ord","age","pre_IP","pre_FIP","pre_ERA","pre_K%","pre_BB%",
             "pre_HR9","prior_FIP","prior_IP"]


def _metrics(y, pred):
    return {"RMSE": float(np.sqrt(mean_squared_error(y, pred))),
            "MAE":  float(mean_absolute_error(y, pred)),
            "R2":   float(r2_score(y, pred))}


def marcel_hitters(df, lg):
    K = 200.0
    lgm = df["season"].map(lg).astype(float)
    base = np.where(df["prior_wOBA"].notna(),
                    0.7*df["prior_wOBA"].fillna(lgm) + 0.3*lgm, lgm)
    r = df["pre_PA"] / (df["pre_PA"] + K)
    age_adj = (27 - df["age"].fillna(27)) * 0.001
    return r*df["pre_wOBA"] + (1-r)*base + age_adj


def marcel_pitchers(df, lg):
    K = 60.0
    lgm = df["season"].map(lg).astype(float)
    base = np.where(df["prior_FIP"].notna(),
                    0.7*df["prior_FIP"].fillna(lgm) + 0.3*lgm, lgm)
    r = df["pre_IP"] / (df["pre_IP"] + K)
    age_adj = (df["age"].fillna(27) - 27) * 0.01          # older -> slightly worse FIP
    return r*df["pre_FIP"] + (1-r)*base + age_adj


def run(kind, df, feats, target, naive_col, lg, marcel_fn):
    df = df.copy()
    df["cutoff_ord"] = df["cutoff"].map(CUTOFF_ORD)
    tr = df[df["season"] < HOLDOUT_SEASON]
    te = df[df["season"] == HOLDOUT_SEASON]
    yte = te[target].values
    w_tr = tr[("post_PA" if kind == "hitters" else "post_IP")].values

    def _ridge():
        return Pipeline([("imp", SimpleImputer(strategy="median")),
                         ("sc", StandardScaler()),
                         ("m", Ridge(alpha=5.0))])

    def _gbm():
        return HistGradientBoostingRegressor(
            max_depth=3, learning_rate=0.05, max_iter=400,
            l2_regularization=1.0, min_samples_leaf=30, random_state=42)

    def _fit(model, X, y, w):
        # pipelines need the step-prefixed weight kwarg
        if isinstance(model, Pipeline):
            model.fit(X, y, m__sample_weight=w)
        else:
            model.fit(X, y, sample_weight=w)
        return model

    results = {}
    # 1. Naive
    results["Naive (current stat)"] = _metrics(yte, te[naive_col].values)
    # 2. Marcel baseline
    results["Marcel baseline"] = _metrics(yte, marcel_fn(te, lg).values)
    # 3. Ridge   4. Gradient boosting
    fitted = {}
    for name, maker in [("Ridge regression", _ridge), ("Gradient boosting", _gbm)]:
        m = _fit(maker(), tr[feats], tr[target], w_tr)
        fitted[name] = m
        results[name] = _metrics(yte, m.predict(te[feats]))

    # pick the winning model TYPE by holdout RMSE, then retrain it on ALL data
    winner = min(("Ridge regression", "Gradient boosting"),
                 key=lambda n: results[n]["RMSE"])

    # permutation importance on the winner (holdout-fitted)
    pim = permutation_importance(fitted[winner], te[feats], yte, n_repeats=10,
                                 random_state=42, scoring="neg_root_mean_squared_error")
    imp = (pd.DataFrame({"kind": kind, "feature": feats,
                         "importance": pim.importances_mean})
           .sort_values("importance", ascending=False))

    full = df
    w_full = full[("post_PA" if kind == "hitters" else "post_IP")].values
    final = _fit((_ridge() if winner == "Ridge regression" else _gbm()),
                 full[feats], full[target], w_full)
    joblib.dump({"model": final, "feats": feats, "target": target, "type": winner},
                OUT / f"proj_model_{kind}.joblib")

    results["_deployed"] = winner
    return results, imp, len(tr), len(te)


def _print_table(kind, res, n_tr, n_te):
    print(f"\n=== {kind.upper()}  (train n={n_tr}, holdout {HOLDOUT_SEASON} n={n_te}) ===")
    print(f"  {'model':24s} {'RMSE':>8s} {'MAE':>8s} {'R2':>7s}")
    rows = {k: v for k, v in res.items() if not k.startswith("_")}
    for name, m in rows.items():
        print(f"  {name:24s} {m['RMSE']:8.4f} {m['MAE']:8.4f} {m['R2']:7.3f}")
    best = min(rows, key=lambda k: rows[k]["RMSE"])
    base = rows["Marcel baseline"]["RMSE"]; bestml = rows[best]["RMSE"]
    lift = (base - bestml) / base * 100
    print(f"  -> best: {best} (deployed: {res.get('_deployed', best)})"
          f"   |   best ML vs Marcel RMSE: {lift:+.1f}%")


def main():
    hit = pd.read_csv(OUT / "proj_train_hitters.csv")
    pit = pd.read_csv(OUT / "proj_train_pitchers.csv")
    const = pd.read_csv(OUT / "proj_league_constants.csv")
    lg_woba = dict(zip(const["season"], const["lg_wOBA"]))
    lg_fip  = dict(zip(const["season"], const["lg_ERA"]))   # FIP is scaled to league ERA

    hres, himp, hntr, hnte = run("hitters", hit, HIT_FEATS, "target_wOBA",
                                 "pre_wOBA", lg_woba, marcel_hitters)
    pres, pimp, pntr, pnte = run("pitchers", pit, PIT_FEATS, "target_FIP",
                                 "pre_FIP", lg_fip, marcel_pitchers)

    _print_table("hitters", hres, hntr, hnte)
    _print_table("pitchers", pres, pntr, pnte)

    imp = pd.concat([himp, pimp], ignore_index=True)
    imp.to_csv(OUT / "proj_feature_importance.csv", index=False)
    print("\nTop hitter features:")
    for _, r in himp.head(5).iterrows():
        print(f"  {r['feature']:14s} {r['importance']:.5f}")
    print("Top pitcher features:")
    for _, r in pimp.head(5).iterrows():
        print(f"  {r['feature']:14s} {r['importance']:.5f}")

    metrics = {"holdout_season": HOLDOUT_SEASON,
               "hitters": hres, "pitchers": pres,
               "n_train": {"hitters": hntr, "pitchers": pntr},
               "n_holdout": {"hitters": hnte, "pitchers": pnte}}
    (OUT / "proj_model_metrics.json").write_text(json.dumps(metrics, indent=2))
    print("\nSaved: proj_model_metrics.json, proj_feature_importance.csv, "
          "proj_model_hitters.joblib, proj_model_pitchers.joblib")


if __name__ == "__main__":
    main()
