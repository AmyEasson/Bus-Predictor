#!/usr/bin/env python3
"""
train.py - train the delay model and prove it beats simple rules.

Trains three LightGBM quantile models predicting the delay at a downstream stop:
    P10 (optimistic), P50 (typical), P90 (pessimistic / "be safe")
so the routing engine can rank options by reliability, not just the average.

It also reports, on held-out LATER data (time split, never random):
  * baselines vs model   - mean absolute error of the "typical" prediction
  * calibration          - is the real delay above P90 about 10% of the time?
  * ablation             - does each feature group (time, live, weather, calendar, events) help?
  * importance           - which features drive predictions (LightGBM's built-in SHAP values)

Usage (from the project root):
    python3 delay_engine/model/train.py
    python3 delay_engine/model/train.py --pairs delay_engine/model/out/pairs.parquet \
        --models delay_engine/model/models/
"""
import argparse
import json
import os
import sys

import lightgbm as lgb
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import features as F  # noqa: E402

QUANTILES = (0.1, 0.5, 0.9)
TEST_FRACTION = 0.2          # last 20% of the time range is held out for testing
PARAMS = dict(n_estimators=400, learning_rate=0.05, num_leaves=31, min_child_samples=20,
              subsample=0.8, subsample_freq=1, colsample_bytree=0.8, verbose=-1)


def prepare(df, categories=None):
    """Make categorical columns consistent. At predict time the SAME category lists must be used,
    so they're saved with the model (categories -> metadata.json)."""
    df = df.copy()
    categories = categories or {c: sorted(df[c].astype(str).unique()) for c in F.CATEGORICAL}
    for c in F.CATEGORICAL:
        df[c] = pd.Categorical(df[c].astype(str), categories=categories[c])
    return df, categories


def usable(df, cols):
    """Keep only feature columns that actually have data (e.g. no context file -> skip that group)."""
    return [c for c in cols if c in df and df[c].notna().any() and df[c].nunique() > 1]


def fit(train, feats, q):
    m = lgb.LGBMRegressor(objective="quantile", alpha=q, **PARAMS)
    m.fit(train[feats], train.target_delay_s)
    return m


def baselines(train, test):
    """Simple rules the model has to beat."""
    out = {"timetable (delay = 0)": np.zeros(len(test)),
           "stays as late as now": test.delay_now_s.values}
    # Historical median for this route/direction/stop/hour, falling back to coarser groups
    keys = [["route", "direction", "to_stop", "hour"], ["route", "direction", "to_stop"],
            ["route", "direction"]]
    pred = pd.Series(np.nan, index=test.index)
    for k in keys:
        med = train.groupby(k, observed=True).target_delay_s.median().rename("m")
        fill = test[k].merge(med, left_on=k, right_index=True, how="left").m
        pred = pred.fillna(fill)
    out["historical median"] = pred.fillna(train.target_delay_s.median()).values
    return out


def mae(y, p):
    return float(np.mean(np.abs(y - p)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pairs", default="delay_engine/model/out/pairs.parquet")
    ap.add_argument("--models", default="delay_engine/model/models/")
    a = ap.parse_args()

    p = pd.read_parquet(a.pairs).dropna(subset=["target_delay_s", "delay_now_s"])
    p, categories = prepare(p)

    # ---- time split: train on earlier data, test on the latest ----------------------------
    cut = p.now_utc.quantile(1 - TEST_FRACTION)
    train, test = p[p.now_utc < cut], p[p.now_utc >= cut]
    # Runs straddling the cut would leak - drop test rows whose run also appears in train
    test = test[~test.run_id.isin(set(train.run_id))]
    print(f"train: {len(train):,} pairs ({train.run_id.nunique():,} runs)  |  "
          f"test: {len(test):,} pairs ({test.run_id.nunique():,} runs), from {cut}")
    if len(test) < 200:
        print("WARNING: very small test set - wait for more data before trusting the numbers")
    y = test.target_delay_s.values

    # ---- feature groups that have data ------------------------------------------------------
    groups = {"core": usable(p, F.CORE), "time": usable(p, F.TIME), "live": usable(p, F.LIVE),
              "weather": usable(p, F.WEATHER), "calendar": usable(p, F.CALENDAR),
              "events": usable(p, F.EVENTS)}
    skipped = [g for g in ("weather", "calendar", "events") if not groups[g]]
    if skipped:
        print(f"skipping {', '.join(skipped)}: no data or no variation in this period")

    # ---- ablation: add groups one at a time, P50 only ---------------------------------------
    print("\nAblation (typical-delay error on test data, lower is better):")
    ablation, feats = {}, []
    for g in ("core", "time", "live", "weather", "calendar", "events"):
        if not groups[g]:
            continue
        feats = feats + groups[g]
        m = fit(train, feats, 0.5)
        ablation[g] = mae(y, m.predict(test[feats]))
        print(f"  + {g:8s} -> {ablation[g]:6.1f} s")
    # Final feature set = every group with data. If the ablation shows a group making things
    # worse, take it out of the tuple in the loop above and re-run.
    final_feats = feats

    # ---- final quantile models -----------------------------------------------------------
    models = {q: fit(train, final_feats, q) for q in QUANTILES}
    pred = {q: models[q].predict(test[final_feats]) for q in QUANTILES}
    # Quantile models are trained separately and can cross; sort so P10 <= P50 <= P90
    stacked = np.sort(np.vstack([pred[q] for q in QUANTILES]), axis=0)
    pred = dict(zip(QUANTILES, stacked))

    # ---- baselines vs model --------------------------------------------------------------
    print("\nTypical-delay error on test data (mean absolute error, seconds):")
    results = {name: mae(y, b) for name, b in baselines(train, test).items()}
    results["MODEL (P50)"] = mae(y, pred[0.5])
    best_baseline = min(v for k, v in results.items() if k != "MODEL (P50)")
    for k, v in results.items():
        print(f"  {k:24s} {v:6.1f} s")
    gain = 1 - results["MODEL (P50)"] / best_baseline
    print(f"  -> model is {gain:.0%} {'better' if gain > 0 else 'WORSE'} than the best baseline")

    # ---- calibration ---------------------------------------------------------------------
    above_p90 = float(np.mean(y > pred[0.9]))
    inside = float(np.mean((y >= pred[0.1]) & (y <= pred[0.9])))
    print(f"\nCalibration: real delay above P90 {above_p90:.0%} of the time (target ~10%), "
          f"inside P10-P90 {inside:.0%} (target ~80%)")

    # ---- importance (mean |SHAP| from LightGBM's built-in contributions) ------------------
    contrib = models[0.5].booster_.predict(test[final_feats], pred_contrib=True)[:, :-1]
    imp = pd.Series(np.abs(contrib).mean(axis=0), index=final_feats).sort_values(ascending=False)
    print("\nWhat drives the prediction (mean |effect| in seconds):")
    for f, v in imp.head(12).items():
        print(f"  {f:22s} {v:6.1f}")

    # ---- save ----------------------------------------------------------------------------
    os.makedirs(a.models, exist_ok=True)
    for q, m in models.items():
        m.booster_.save_model(os.path.join(a.models, f"delay_q{int(q * 100):02d}.txt"))
    meta = {"features": final_feats, "categorical": F.CATEGORICAL, "categories": categories,
            "quantiles": list(QUANTILES), "trained_until": str(cut),
            "n_train": len(train), "n_test": len(test),
            "mae_s": results, "ablation_mae_s": ablation,
            "calibration": {"above_p90": above_p90, "inside_p10_p90": inside},
            "importance_s": imp.round(2).to_dict()}
    with open(os.path.join(a.models, "metadata.json"), "w") as f:
        json.dump(meta, f, indent=2, default=str)
    test.assign(p10=pred[0.1], p50=pred[0.5], p90=pred[0.9]) \
        .to_parquet(os.path.join(a.models, "test_predictions.parquet"), index=False)
    print(f"\nSaved models + metadata.json + test_predictions.parquet to {a.models}")


if __name__ == "__main__":
    main()