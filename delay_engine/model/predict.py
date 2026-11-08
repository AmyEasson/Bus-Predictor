#!/usr/bin/env python3
"""
predict.py - use the trained delay model. This is what the routing engine imports.

    from predict import DelayModel
    model = DelayModel("delay_engine/model/models/")
    r = model.predict_arrival(
        route="43", direction="0", to_stop="1800SB12345", to_lat=53.46, to_lon=-2.23,
        now_utc=pd.Timestamp.now(tz="UTC"),
        delay_now_s=120,                 # how late the bus is right now
        stops_ahead=6,                   # stops between where it is and where you're going
        sched_travel_s=540,              # timetabled time for that stretch
        scheduled_arrival_utc=pd.Timestamp("2026-11-07T18:30:00Z"),
    )
    r["arrival_p50"], r["arrival_p90"]  # typical and "be safe" arrival times

Optional extra context (better predictions if you have it):
    recent_arrivals=<stop_arrivals DataFrame from features.load_stop_arrivals>  -> live features
    gap_ahead_s / headway_ratio                                                  -> bunching
Weather, calendar and events are read from context/ (context_hourly.parquet, events.csv)
automatically if the files exist. For live use the hourly file must cover the current hour.

Run directly to print a few test-set predictions next to what actually happened:
    python3 delay_engine/model/predict.py
"""
import json
import os
import sys

import lightgbm as lgb
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import features as F  # noqa: E402


class DelayModel:
    def __init__(self, model_dir="delay_engine/model/models/", context_dir="context/"):
        with open(os.path.join(model_dir, "metadata.json")) as f:
            self.meta = json.load(f)
        self.features = self.meta["features"]
        self.boosters = {q: lgb.Booster(model_file=os.path.join(
            model_dir, f"delay_q{int(q * 100):02d}.txt")) for q in self.meta["quantiles"]}
        self.context = F.load_context_hourly(os.path.join(context_dir, "context_hourly.parquet"))
        self.events = F.load_events(os.path.join(context_dir, "events.csv"))

    def _prepare(self, df):
        """Same categories as training; unseen values (e.g. a new stop) become missing."""
        df = df.copy()
        for c, cats in self.meta["categories"].items():
            df[c] = pd.Categorical(df[c].astype(str), categories=cats)
        for c in self.features:
            if c not in df:
                df[c] = np.nan
        return df

    def predict_frame(self, df):
        """df has one row per prediction with the feature columns (missing ones are fine).
        Returns P10/P50/P90 delay in seconds, sorted so P10 <= P50 <= P90."""
        X = self._prepare(df)[self.features]
        preds = np.vstack([self.boosters[q].predict(X) for q in self.meta["quantiles"]])
        preds = np.sort(preds, axis=0)
        return pd.DataFrame({"delay_p10_s": preds[0], "delay_p50_s": preds[1],
                             "delay_p90_s": preds[2]}, index=df.index)

    def predict_arrival(self, route, direction, to_stop, to_lat, to_lon, now_utc, delay_now_s,
                        stops_ahead, sched_travel_s, scheduled_arrival_utc,
                        recent_arrivals=None, gap_ahead_s=np.nan, headway_ratio=np.nan):
        """Predict when one bus will reach one stop. Returns delays and arrival times."""
        row = pd.DataFrame([{
            "route": str(route), "direction": str(direction), "to_stop": str(to_stop),
            "to_lat": to_lat, "to_lon": to_lon, "now_utc": pd.Timestamp(now_utc),
            "delay_now_s": delay_now_s, "stops_ahead": stops_ahead,
            "sched_travel_s": sched_travel_s, "gap_ahead_s": gap_ahead_s,
            "headway_ratio": headway_ratio}])
        # Same feature code as training -> same meaning
        row = F.add_time_features(row, "now_utc")
        if recent_arrivals is not None:
            row = F.add_live_features(row, recent_arrivals, "now_utc")
        row = F.add_hourly_context(row, self.context, "now_utc")
        row = F.add_events(row, self.events, "now_utc")

        d = self.predict_frame(row).iloc[0]
        sched = pd.Timestamp(scheduled_arrival_utc)
        return {
            "delay_p10_s": float(d.delay_p10_s), "delay_p50_s": float(d.delay_p50_s),
            "delay_p90_s": float(d.delay_p90_s),
            "arrival_p10": sched + pd.Timedelta(seconds=float(d.delay_p10_s)),
            "arrival_p50": sched + pd.Timedelta(seconds=float(d.delay_p50_s)),
            "arrival_p90": sched + pd.Timedelta(seconds=float(d.delay_p90_s)),
        }


if __name__ == "__main__":
    # Demo: show a handful of held-out predictions next to what really happened
    model_dir = sys.argv[1] if len(sys.argv) > 1 else "delay_engine/model/models/"
    tp = pd.read_parquet(os.path.join(model_dir, "test_predictions.parquet"))
    ex = tp.sample(min(8, len(tp)), random_state=1)
    print(f"{'route':>5} {'ahead':>5} {'late now':>9} {'P10':>6} {'P50':>6} {'P90':>6} {'actual':>7}")
    for r in ex.itertuples():
        ok = "ok" if r.p10 <= r.target_delay_s <= r.p90 else "outside"
        print(f"{r.route:>5} {r.stops_ahead:>5} {r.delay_now_s / 60:8.1f}m "
              f"{r.p10 / 60:5.1f}m {r.p50 / 60:5.1f}m {r.p90 / 60:5.1f}m "
              f"{r.target_delay_s / 60:6.1f}m  {ok}")