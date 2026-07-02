"""
Data Quality Monitor - Web Interface
Flask app that wraps the quality engine with a clean UI.
Upload any file → see results as a visual dashboard.
"""

import os
import sys
import json
import yaml
from datetime import datetime
from flask import Flask, request, render_template, redirect, url_for, send_file

# make sure project root is importable
PROJECT_ROOT = os.path.abspath(os.path.dirname(__file__))
sys.path.insert(0, PROJECT_ROOT)

from engine import QualityEngine
from report_generator import ReportGenerator
from result_store import ResultStore
from ml.forecast import load_forecast_bundle, predict_next, trend_label

app = Flask(__name__)
app.config["UPLOAD_FOLDER"] = os.path.join(PROJECT_ROOT, "uploads")
app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024  # 50MB max upload

# create folders if they don't exist
os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)
os.makedirs(os.path.join(PROJECT_ROOT, "flagged_records"), exist_ok=True)
os.makedirs(os.path.join(PROJECT_ROOT, "reports"), exist_ok=True)

# allowed file extensions
ALLOWED_EXTENSIONS = {".csv", ".xlsx", ".xls", ".json"}


def allowed_file(filename):
    return os.path.splitext(filename)[1].lower() in ALLOWED_EXTENSIONS


def get_available_configs():
    """List all YAML config files in configs/ folder."""
    config_dir = os.path.join(PROJECT_ROOT, "configs")
    if not os.path.exists(config_dir):
        return []
    return [f for f in os.listdir(config_dir) if f.endswith((".yaml", ".yml"))]


def get_available_checks():
    """Get list of all registered checks with metadata."""
    from checks.registry import CheckRegistry

    registry = CheckRegistry()
    return registry.list_checks()


def build_forecast_chart_data(data_source, n_ahead=3):
    """
    Build a Chart.js-ready payload combining historical scores with a
    forecasted continuation, for one data source.

    Returns None if there's no trained forecast model yet (not enough
    history) — the template handles that by showing a "not enough data"
    message instead of an empty chart.
    """
    if not data_source or data_source == "unknown":
        return None

    store = ResultStore()
    history = store.get_score_history(data_source)
    bundle = load_forecast_bundle("models", data_source)

    if not bundle:
        return {
            "available": False,
            "n_runs": len(history),
            "min_required": 10,
        }

    predicted_scores = predict_next(bundle, n_ahead=n_ahead)
    trend = trend_label(bundle["slope"])

    # Multiple runs can land on the same calendar day (e.g. repeated manual
    # testing). The forecast MODEL is still trained on full history in
    # train_models.py — this dedup is display-only, so the chart reads as
    # one point per day instead of stacking dozens of same-day dots.
    # history is chronologically ordered, so "last one wins" keeps the most
    # recent run for any day that had multiple.
    daily = {}
    for h in history:
        day = h["run_timestamp"][:10]
        daily[day] = h["overall_score"]

    actual_labels = list(daily.keys())
    actual_scores = list(daily.values())
    forecast_labels = [f"+{i}" for i in range(1, n_ahead + 1)]

    # Chart.js draws one continuous line per dataset. To show a dashed
    # "future" segment connected to the solid "actual" line, the forecast
    # dataset starts with nulls for every actual point except the last
    # (so the two lines visually connect) then carries the predicted values.
    forecast_series = (
        [None] * (len(actual_scores) - 1) + [actual_scores[-1]] + predicted_scores
    )

    return {
        "available": True,
        "labels": actual_labels + forecast_labels,
        "actual": actual_scores + [None] * n_ahead,
        "forecast": forecast_series,
        "trend": trend,
        "slope": round(bundle["slope"], 3),
        "n_runs": bundle["n_runs"],
        "predicted_scores": predicted_scores,
    }


# ---- Routes ----


@app.route("/")
def upload_page():
    """Page 1: Upload file + select config + choose checks."""
    configs = get_available_configs()
    checks = get_available_checks()
    return render_template("upload.html", configs=configs, checks=checks)


@app.route("/check", methods=["POST"])
def run_check():
    """Handle file upload, run quality checks, redirect to results."""

    # --- validate file upload ---
    if "file" not in request.files:
        return redirect(url_for("upload_page"))

    file = request.files["file"]
    if file.filename == "" or not allowed_file(file.filename):
        return redirect(url_for("upload_page"))

    # save uploaded file
    filename = file.filename
    filepath = os.path.join(app.config["UPLOAD_FOLDER"], filename)
    file.save(filepath)

    # --- handle config ---
    config_path = None

    # check if user uploaded a custom config
    if "config_file" in request.files:
        config_file = request.files["config_file"]
        if config_file.filename != "":
            config_path = os.path.join(
                app.config["UPLOAD_FOLDER"], "custom_config.yaml"
            )
            config_file.save(config_path)

    # if no custom config, check dropdown selection
    if not config_path:
        selected_config = request.form.get("config_select", "")
        if selected_config and selected_config != "default":
            config_path = os.path.join(PROJECT_ROOT, "configs", selected_config)

    # --- handle check selection ---
    selected_checks = request.form.getlist("checks")

    # if specific checks selected, create a temporary config override
    if selected_checks and config_path:
        with open(config_path, "r") as f:
            config = yaml.safe_load(f) or {}
        config["checks"] = {"enabled": selected_checks, "disabled": []}
        config_path = os.path.join(app.config["UPLOAD_FOLDER"], "temp_config.yaml")
        with open(config_path, "w") as f:
            yaml.dump(config, f)
    elif selected_checks:
        config_path = os.path.join(app.config["UPLOAD_FOLDER"], "temp_config.yaml")
        config = {"checks": {"enabled": selected_checks, "disabled": []}}
        with open(config_path, "w") as f:
            yaml.dump(config, f)

    # --- run the engine ---
    engine = QualityEngine()
    report = engine.run(filepath=filepath, config_path=config_path, parallel=True)

    # export flagged records CSV
    csv_path = engine.export_flagged_csv(report)

    # save text report
    reporter = ReportGenerator()
    txt_path = reporter.save_report(report, verbose=True)

    # store report in session-like temp file for the results page
    report_path = os.path.join(app.config["UPLOAD_FOLDER"], "last_report.json")
    # convert report to JSON-safe format
    with open(report_path, "w") as f:
        json.dump(report, f, default=str)

    return redirect(url_for("results_page"))


@app.route("/results")
def results_page():
    """Page 2: Results dashboard with full details."""
    report_path = os.path.join(app.config["UPLOAD_FOLDER"], "last_report.json")

    if not os.path.exists(report_path):
        return redirect(url_for("upload_page"))

    with open(report_path, "r") as f:
        report = json.load(f)

    # fix types from JSON deserialization (JSON stores everything as strings)
    report["rows"] = int(report.get("rows", 0))
    report["columns"] = int(report.get("columns", 0))
    report["checks_run"] = int(report.get("checks_run", 0))
    for r in report.get("results", []):
        r["passed"] = r["passed"] in (True, "True", "true")
        r["issue_count"] = int(r.get("issue_count", 0))
        r["total_checked"] = int(r.get("total_checked", 0))
        r["issue_pct"] = float(r.get("issue_pct", 0))
        r["flagged_count"] = int(r.get("flagged_count", 0))

    # sort results: failed first, by severity
    severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    report["results"] = sorted(
        report["results"],
        key=lambda r: (
            str(r["passed"]) == "True" or r["passed"] is True,
            severity_order.get(r["severity"], 99),
        ),
    )

    # get run history for the history section
    engine = QualityEngine()
    history = engine.get_history(limit=20)

    # ML score forecast for this data source (None-safe — handled in template)
    forecast = build_forecast_chart_data(report.get("data_source"))

    return render_template(
        "results.html", report=report, history=history, forecast=forecast
    )


@app.route("/download/<file_type>")
def download_file(file_type):
    """Download flagged records CSV or text report."""
    if file_type == "csv":
        # find latest flagged records file
        folder = os.path.join(PROJECT_ROOT, "flagged_records")
        files = (
            sorted(os.listdir(folder), reverse=True) if os.path.exists(folder) else []
        )
        if files:
            return send_file(os.path.join(folder, files[0]), as_attachment=True)
    elif file_type == "report":
        folder = os.path.join(PROJECT_ROOT, "reports")
        files = (
            sorted(os.listdir(folder), reverse=True) if os.path.exists(folder) else []
        )
        if files:
            return send_file(os.path.join(folder, files[0]), as_attachment=True)

    return redirect(url_for("results_page"))


@app.route("/history")
def history_api():
    """Return run history as JSON (for AJAX calls)."""
    engine = QualityEngine()
    history = engine.get_history(limit=50)
    return json.dumps(history, default=str)


# ---- Run ----

if __name__ == "__main__":
    print("\n  Data Quality Monitor")
    print("  Open http://127.0.0.1:5000 in your browser\n")
    app.run(debug=True, port=5000)
