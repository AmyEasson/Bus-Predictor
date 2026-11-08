
#!/usr/bin/env python3
"""
train.py - train the delay model and evaluate it on held-out future data.

Trains three LightGBM quantile models:
    P10 (optimistic), P50 (typical), P90 (pessimistic).

The test set is chronological. Training examples are only included if
their target arrival was observed before the test period begins.
Runs appearing in training are excluded from testing.
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
TEST_FRACTION = 0.2

PARAMS = dict(
    n_estimators=400,
    learning_rate=0.05,
    num_leaves=31,
    min_child_samples=20,
    subsample=0.8,
    subsample_freq=1,
    colsample_bytree=0.8,
    verbose=-1,
)


def prepare(df, categories=None):
    """Make categorical columns consistent between training and testing."""
    df = df.copy()

    if categories is None:
        categories = {}
        for c in F.CATEGORICAL:
            values = df[c].astype("string").dropna().unique()
            categories[c] = sorted(values.tolist())

    for c in F.CATEGORICAL:
        values = df[c].astype("string")

        # Unseen test categories become missing values.
        values = values.where(values.isin(categories[c]))

        df[c] = pd.Categorical(
            values,
            categories=categories[c],
        )

    return df, categories


def usable(df, cols):
    """Keep feature columns with data and variation in the training set."""
    return [
        c for c in cols
        if c in df and df[c].notna().any() and df[c].nunique() > 1
    ]


def fit(train, feats, q):
    model = lgb.LGBMRegressor(
        objective="quantile",
        alpha=q,
        **PARAMS,
    )
    model.fit(train[feats], train.target_delay_s)
    return model


def baselines(train, test):
    """Simple rules the model has to beat."""
    out = {
        "timetable (delay = 0)": np.zeros(len(test)),
        "stays as late as now": test.delay_now_s.values,
    }

    keys = [
        ["route", "direction", "to_stop", "hour"],
        ["route", "direction", "to_stop"],
        ["route", "direction"],
    ]

    pred = pd.Series(np.nan, index=test.index)

    for k in keys:
        med = (
            train.groupby(k, observed=True)
            .target_delay_s.median()
            .rename("m")
        )
        fill = test[k].merge(
            med,
            left_on=k,
            right_index=True,
            how="left",
        ).m
        pred = pred.fillna(fill)

    out["historical median"] = (
        pred.fillna(train.target_delay_s.median()).values
    )

    return out


def mae(y, p):
    return float(np.mean(np.abs(y - p)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--pairs",
        default="delay_engine/model/out/pairs.parquet",
    )
    ap.add_argument(
        "--models",
        default="delay_engine/model/models/",
    )
    args = ap.parse_args()

    # ---- Load pairs ---------------------------------------------------------
    p = pd.read_parquet(args.pairs).dropna(
        subset=["target_delay_s", "delay_now_s"]
    )

    # Ensure both timestamps are timezone-aware UTC.
    p["now_utc"] = pd.to_datetime(p["now_utc"], utc=True)
    p["actual_to"] = pd.to_datetime(p["actual_to"], utc=True)

    # ---- Strict chronological split ----------------------------------------
    cut = p.now_utc.quantile(1 - TEST_FRACTION)

    # Training labels must have been observed before the test period.
    train = p[
        (p.now_utc < cut)
        & (p.actual_to < cut)
    ].copy()

    # Test predictions begin at or after the cutoff.
    test = p[p.now_utc >= cut].copy()

    # Exclude test examples from runs represented in training.
    train_runs = set(train.run_id)
    test = test[~test.run_id.isin(train_runs)].copy()

    # Fit categorical vocabularies using training data only.
    train, categories = prepare(train)
    test, _ = prepare(test, categories)

    print(
        f"Cutoff: {cut}\n"
        f"train: {len(train):,} pairs "
        f"({train.run_id.nunique():,} runs)  |  "
        f"test: {len(test):,} pairs "
        f"({test.run_id.nunique():,} runs)"
    )

    if len(train) == 0 or len(test) == 0:
        raise ValueError("Training or test set is empty after temporal split.")

    if not (train.actual_to < cut).all():
        raise AssertionError("Training contains target arrivals after cutoff.")

    if not (test.now_utc >= cut).all():
        raise AssertionError("Test contains predictions before cutoff.")

    if set(train.run_id) & set(test.run_id):
        raise AssertionError("A run appears in both training and testing.")

    if len(test) < 200:
        print("WARNING: very small test set.")

    y = test.target_delay_s.values

    # ---- Feature groups -----------------------------------------------------
    groups = {
        "core": usable(train, F.CORE),
        "time": usable(train, F.TIME),
        "live": usable(train, F.LIVE),
        "weather": usable(train, F.WEATHER),
        "calendar": usable(train, F.CALENDAR),
        "events": usable(train, F.EVENTS),
    }

    skipped = [
        g for g in ("weather", "calendar", "events")
        if not groups[g]
    ]

    if skipped:
        print(f"Skipping {', '.join(skipped)}: no training data or variation.")

    # ---- Ablation -----------------------------------------------------------
    print("\nAblation (typical-delay error on test data, lower is better):")

    ablation = {}
    feats = []

    for group in ("core", "time", "live", "weather", "calendar", "events"):
        if not groups[group]:
            continue

        feats += groups[group]
        model = fit(train, feats, 0.5)
        ablation[group] = mae(y, model.predict(test[feats]))

        print(f"  + {group:8s} -> {ablation[group]:6.1f} s")

    final_feats = feats

    # ---- Final quantile models ---------------------------------------------
    models = {
        q: fit(train, final_feats, q)
        for q in QUANTILES
    }

    pred = {
        q: models[q].predict(test[final_feats])
        for q in QUANTILES
    }

    # Ensure P10 <= P50 <= P90.
    stacked = np.sort(
        np.vstack([pred[q] for q in QUANTILES]),
        axis=0,
    )
    pred = dict(zip(QUANTILES, stacked))

    # ---- Baselines ----------------------------------------------------------
    print("\nTypical-delay error on test data (mean absolute error, seconds):")

    results = {
        name: mae(y, baseline)
        for name, baseline in baselines(train, test).items()
    }

    results["MODEL (P50)"] = mae(y, pred[0.5])

    best_baseline = min(
        v for k, v in results.items()
        if k != "MODEL (P50)"
    )

    for name, value in results.items():
        print(f"  {name:24s} {value:6.1f} s")

    gain = 1 - results["MODEL (P50)"] / best_baseline

    print(
        f"  -> model is {gain:.0%} "
        f"{'better' if gain > 0 else 'WORSE'} than the best baseline"
    )

    # ---- Calibration --------------------------------------------------------
    above_p90 = float(np.mean(y > pred[0.9]))
    inside = float(
        np.mean((y >= pred[0.1]) & (y <= pred[0.9]))
    )

    print(
        f"\nCalibration: real delay above P90 {above_p90:.0%} "
        f"(target ~10%), inside P10-P90 {inside:.0%} "
        f"(target ~80%)"
    )

    # ---- Feature importance -------------------------------------------------
    contrib = models[0.5].booster_.predict(
        test[final_feats],
        pred_contrib=True,
    )[:, :-1]

    imp = (
        pd.Series(
            np.abs(contrib).mean(axis=0),
            index=final_feats,
        )
        .sort_values(ascending=False)
    )

    print("\nWhat drives the prediction (mean |effect| in seconds):")

    for feature, value in imp.head(12).items():
        print(f"  {feature:22s} {value:6.1f}")

    # ---- Save ---------------------------------------------------------------
    os.makedirs(args.models, exist_ok=True)

    for q, model in models.items():
        model.booster_.save_model(
            os.path.join(args.models, f"delay_q{int(q * 100):02d}.txt")
        )

    meta = {
        "features": final_feats,
        "categorical": F.CATEGORICAL,
        "categories": categories,
        "quantiles": list(QUANTILES),
        "trained_until": str(cut),
        "n_train": len(train),
        "n_test": len(test),
        "mae_s": results,
        "ablation_mae_s": ablation,
        "calibration": {
            "above_p90": above_p90,
            "inside_p10_p90": inside,
        },
        "importance_s": imp.round(2).to_dict(),
    }

    with open(os.path.join(args.models, "metadata.json"), "w") as f:
        json.dump(meta, f, indent=2, default=str)

    test.assign(
        p10=pred[0.1],
        p50=pred[0.5],
        p90=pred[0.9],
    ).to_parquet(
        os.path.join(args.models, "test_predictions.parquet"),
        index=False,
    )

    print(f"\nSaved models + metadata.json + test_predictions.parquet to {args.models}")


if __name__ == "__main__":
    main()
