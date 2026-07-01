"""
Train ML models (anomaly detection + score forecasting) from historical run data.

Reads column_profiles and runs history from SQLite per data source, fits an
anomaly model per numeric column and a score-forecast model per data source,
and saves them to models/ for the AnomalyDetectionCheck and --forecast to load.

Usage:
    python train_models.py                       # train all data sources
    python train_models.py --data-source hr_system
    python train_models.py --db db/quality_results.db --models-dir models
"""

import argparse

from result_store import ResultStore
from ml import MIN_HISTORY_RUNS
from ml.anomaly import train_anomaly_models, save_anomaly_bundle
from ml.forecast import train_forecast_model, save_forecast_bundle


def train_data_source(store: ResultStore, data_source: str, models_dir: str):
    print(f"  {data_source}:")

    profile_rows = store.get_column_profile_history(data_source)
    anomaly_bundle = train_anomaly_models(profile_rows)
    if anomaly_bundle["columns"]:
        path = save_anomaly_bundle(anomaly_bundle, models_dir, data_source)
        cols = ", ".join(anomaly_bundle["columns"].keys())
        print(f"    anomaly model: trained {len(anomaly_bundle['columns'])} column(s) [{cols}] -> {path}")
    else:
        print(f"    anomaly model: skipped (no numeric column has >= {MIN_HISTORY_RUNS} historical runs)")

    score_rows = store.get_score_history(data_source)
    forecast_bundle = train_forecast_model(score_rows)
    if forecast_bundle:
        path = save_forecast_bundle(forecast_bundle, models_dir, data_source)
        print(f"    forecast model: trained on {forecast_bundle['n_runs']} runs -> {path}")
    else:
        print(f"    forecast model: skipped (only {len(score_rows)} runs, need >= {MIN_HISTORY_RUNS})")


def main():
    parser = argparse.ArgumentParser(description="Train anomaly detection and score forecasting models")
    parser.add_argument("--db", default="db/quality_results.db", help="Path to SQLite database")
    parser.add_argument("--models-dir", default="models", help="Output directory for trained models")
    parser.add_argument("--data-source", help="Train only this data source (default: all)")
    args = parser.parse_args()

    store = ResultStore(db_path=args.db)
    sources = [args.data_source] if args.data_source else store.list_data_sources()

    if not sources:
        print("No data sources found in the database. Run some checks first.")
        return

    print(f"Training models for {len(sources)} data source(s): {', '.join(sources)}\n")
    for data_source in sources:
        train_data_source(store, data_source, args.models_dir)

    print(f"\nDone. Models saved to {args.models_dir}/")


if __name__ == "__main__":
    main()
