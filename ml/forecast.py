# Score trend forecasting: fits a simple linear trend of overall_score over
# run sequence per data source, so future quality drops can be predicted.

import os
from datetime import datetime
from typing import Optional

import joblib
import numpy as np

from . import MIN_HISTORY_RUNS


def train_forecast_model(score_rows: list) -> Optional[dict]:
    """
    score_rows: list of dicts with run_timestamp, overall_score, chronologically ordered
    (as returned by ResultStore.get_score_history). Returns None if not enough history.
    """
    if len(score_rows) < MIN_HISTORY_RUNS:
        return None

    scores = np.array([r["overall_score"] for r in score_rows], dtype=float)
    x = np.arange(len(scores))
    slope, intercept = np.polyfit(x, scores, 1)

    return {
        "slope": float(slope),
        "intercept": float(intercept),
        "n_runs": len(scores),
        "last_index": int(x[-1]),
        "last_score": float(scores[-1]),
        "trained_at": datetime.now().isoformat(),
    }


def save_forecast_bundle(bundle: dict, models_dir: str, data_source: str) -> str:
    os.makedirs(models_dir, exist_ok=True)
    path = os.path.join(models_dir, f"{data_source}_forecast.joblib")
    joblib.dump(bundle, path)
    return path


def load_forecast_bundle(models_dir: str, data_source: str) -> Optional[dict]:
    path = os.path.join(models_dir, f"{data_source}_forecast.joblib")
    if not os.path.exists(path):
        return None
    return joblib.load(path)


def predict_next(bundle: dict, n_ahead: int = 3) -> list:
    """Linearly extrapolate the next n_ahead scores, clipped to [0, 100]."""
    future_x = [bundle["last_index"] + i for i in range(1, n_ahead + 1)]
    predicted = [bundle["slope"] * x + bundle["intercept"] for x in future_x]
    return [round(max(0.0, min(100.0, p)), 2) for p in predicted]


def trend_label(slope: float, epsilon: float = 0.05) -> str:
    if slope > epsilon:
        return "improving"
    if slope < -epsilon:
        return "declining"
    return "stable"
