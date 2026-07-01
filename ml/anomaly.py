# Per-column anomaly models: learns "normal" ranges for a data source's numeric
# columns from historical column_profiles rows, so new runs can be flagged if a
# column's stats (mean/std/null rate/uniqueness) drift outside historical norms.

import os
from datetime import datetime
from typing import Optional

import joblib
from sklearn.ensemble import IsolationForest

from . import MIN_HISTORY_RUNS

NUMERIC_DTYPES = ("int64", "float64")


def build_feature_vector(mean, std, null_count, unique_count, total_count) -> list:
    """Feature vector for one column-profile snapshot. Used identically at train and predict time."""
    null_pct = (null_count / total_count) if total_count else 0.0
    unique_pct = (unique_count / total_count) if total_count else 0.0
    return [mean or 0.0, std or 0.0, null_pct, unique_pct]


def train_anomaly_models(profile_rows: list) -> dict:
    """
    Fit one IsolationForest per numeric column from historical column_profiles rows.

    profile_rows: list of dicts with column_name, dtype, mean, std, null_count,
                  unique_count, total_count (as returned by
                  ResultStore.get_column_profile_history).
    """
    by_column = {}
    for row in profile_rows:
        if row.get("dtype") not in NUMERIC_DTYPES or row.get("mean") is None:
            continue
        by_column.setdefault(row["column_name"], []).append(row)

    columns = {}
    for col, rows in by_column.items():
        if len(rows) < MIN_HISTORY_RUNS:
            continue
        features = [
            build_feature_vector(r["mean"], r["std"], r["null_count"], r["unique_count"], r["total_count"])
            for r in rows
        ]
        model = IsolationForest(n_estimators=100, contamination=0.1, random_state=42)
        model.fit(features)
        columns[col] = {"model": model, "n_samples": len(rows)}

    return {"columns": columns, "trained_at": datetime.now().isoformat()}


def save_anomaly_bundle(bundle: dict, models_dir: str, data_source: str) -> str:
    os.makedirs(models_dir, exist_ok=True)
    path = os.path.join(models_dir, f"{data_source}_anomaly.joblib")
    joblib.dump(bundle, path)
    return path


def load_anomaly_bundle(models_dir: str, data_source: str) -> Optional[dict]:
    path = os.path.join(models_dir, f"{data_source}_anomaly.joblib")
    if not os.path.exists(path):
        return None
    return joblib.load(path)


def predict_column_anomaly(entry: dict, features: list) -> tuple:
    """Returns (is_anomaly, score). Lower decision_function score = more anomalous."""
    model = entry["model"]
    is_anomaly = model.predict([features])[0] == -1
    score = float(model.decision_function([features])[0])
    return is_anomaly, score
