"""
Generate historical quality check data for Power BI dashboards and trend analysis.
Creates multiple data sources with varying quality issues over time,
runs them through the actual engine so all tables (runs, check_results,
flagged_records, column_profiles) get properly populated.

Usage:
    python generate_history.py              # default: 4 sources, ~30 runs each
    python generate_history.py --runs 50    # more runs per source
    python generate_history.py --clean      # wipe db first
"""

import os
import sys
import random
import argparse
import numpy as np
import pandas as pd
from datetime import datetime, timedelta

# resolve project root so imports work when running from data_gen/ subfolder
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, PROJECT_ROOT)
os.chdir(PROJECT_ROOT)  # so db/, reports/, temp files are relative to project root

from engine import QualityEngine


# ---- Common issue injection ----

def inject_common_issues(df, noise_level, text_cols, date_cols):
    """Inject empty strings and future dates into any generated dataset."""
    n = len(df)
    n_issues = max(1, int(n * noise_level))

    # empty strings in text columns - use a single space that gets detected as empty-like
    # but also inject actual empty strings at higher volume since CSV round-trip loses some
    n_empty = max(2, int(n_issues * 0.15))
    for _ in range(n_empty):
        col = random.choice(text_cols)
        row = random.randint(0, n - 1)
        df.loc[row, col] = ""

    # future dates in timestamp columns
    if date_cols:
        n_future = max(1, int(n_issues * 0.08))
        future_dates = ["2030-06-15", "2031-12-31", "2029-03-22", "2032-01-01", "2028-08-10"]
        for _ in range(n_future):
            col = random.choice(date_cols)
            row = random.randint(0, n - 1)
            df.loc[row, col] = random.choice(future_dates)

    return df


# ---- Data generators for each source ----

# Each generator creates a realistic dataset for that domain, then injects quality issues based on the noise_level parameter.

# HR system employee data with realistic distributions and quality issues.
def generate_hr_data(noise_level=0.1):
    n = random.randint(80, 150)
    departments = ["Engineering", "Sales", "Marketing", "HR", "Finance", "Operations"]
    statuses = ["active", "inactive", "pending", "on_leave"]

    df = pd.DataFrame({
        "employee_id": [f"E{i:04d}" for i in range(1, n + 1)],
        "full_name": [f"Employee {i}" for i in range(1, n + 1)],
        "department": [random.choice(departments) for _ in range(n)],
        "email": [f"emp{i}@company.com" for i in range(1, n + 1)],
        "age": np.random.randint(22, 62, size=n).astype(float),
        "salary": np.random.randint(35000, 130000, size=n),
        "performance_rating": np.round(np.random.uniform(1.5, 5.0, size=n), 1),
        "hire_date": pd.date_range(end=datetime.now(), periods=n, freq="12D").strftime("%Y-%m-%d").tolist(),
        "status": [random.choice(statuses) for _ in range(n)],
    })

    n_nulls = int(n * noise_level * 0.5)
    n_range = int(n * noise_level * 0.3)
    n_whitespace = int(n * noise_level * 0.2)
    n_dups = int(n * noise_level * 0.05)

    for _ in range(n_nulls):
        col = random.choice(["full_name", "email", "age", "department", "performance_rating"])
        row = random.randint(0, n - 1)
        df.loc[row, col] = None

    for _ in range(n_range):
        issue_type = random.choice(["age_high", "age_low", "salary_neg", "rating_high"])
        row = random.randint(0, n - 1)
        if issue_type == "age_high":
            df.loc[row, "age"] = random.randint(130, 200)
        elif issue_type == "age_low":
            df.loc[row, "age"] = random.randint(-10, -1)
        elif issue_type == "salary_neg":
            df.loc[row, "salary"] = random.randint(-50000, -1000)
        elif issue_type == "rating_high":
            df.loc[row, "performance_rating"] = round(random.uniform(5.1, 7.0), 1)

    for _ in range(n_whitespace):
        col = random.choice(["full_name", "department", "email"])
        row = random.randint(0, n - 1)
        val = df.loc[row, col]
        if val is not None and isinstance(val, str):
            df.loc[row, col] = f" {val} "

    for _ in range(n_dups):
        src = random.randint(0, n - 1)
        df = pd.concat([df, df.iloc[[src]]], ignore_index=True)

    df = inject_common_issues(df, noise_level,
                               text_cols=["full_name", "department", "email", "status"],
                               date_cols=["hire_date"])
    return df

# Factory IoT sensor data with realistic ranges and quality issues.
def generate_sensor_data(noise_level=0.1):
    n = random.randint(100, 200)
    locations = ["Assembly Line A", "Assembly Line B", "Paint Shop", "Welding Bay",
                 "Quality Lab", "Warehouse", "Loading Dock"]

    df = pd.DataFrame({
        "sensor_id": [f"SNS-{i:03d}" for i in range(1, n + 1)],
        "location": [random.choice(locations) for _ in range(n)],
        "temperature": np.round(np.random.normal(24, 3, size=n), 1),
        "humidity": np.random.randint(40, 80, size=n),
        "pressure": np.round(np.random.normal(1013, 2, size=n), 1),
        "vibration_level": np.round(np.random.exponential(1.5, size=n), 2),
        "battery_pct": np.random.randint(20, 100, size=n),
        "reading_timestamp": pd.date_range(end=datetime.now(), periods=n, freq="5min").strftime("%Y-%m-%d %H:%M:%S").tolist(),
        "status": ["normal"] * n,
    })

    n_issues = int(n * noise_level)

    for _ in range(int(n_issues * 0.3)):
        row = random.randint(0, n - 1)
        col = random.choice(["temperature", "humidity", "pressure", "location", "battery_pct"])
        df.loc[row, col] = None

    for _ in range(int(n_issues * 0.3)):
        row = random.randint(0, n - 1)
        issue = random.choice(["temp_high", "temp_low", "humidity_neg", "humidity_over"])
        if issue == "temp_high":
            df.loc[row, "temperature"] = random.randint(160, 200)
        elif issue == "temp_low":
            df.loc[row, "temperature"] = random.randint(-70, -55)
        elif issue == "humidity_neg":
            df.loc[row, "humidity"] = random.randint(-20, -1)
        elif issue == "humidity_over":
            df.loc[row, "humidity"] = random.randint(105, 130)

    for _ in range(int(n_issues * 0.15)):
        col = random.choice(["location", "status"])
        row = random.randint(0, n - 1)
        val = df.loc[row, col]
        if isinstance(val, str):
            df.loc[row, col] = f" {val}"

    for _ in range(int(n_issues * 0.05)):
        src = random.randint(0, n - 1)
        df = pd.concat([df, df.iloc[[src]]], ignore_index=True)

    df = inject_common_issues(df, noise_level,
                               text_cols=["location", "status"],
                               date_cols=["reading_timestamp"])
    return df

# ERP procurement data with realistic distributions and quality issues.
def generate_procurement_data(noise_level=0.1):
    n = random.randint(60, 120)
    suppliers = ["Apex Industrial", "ClearFlow", "TransDrive", "MetroSteel",
                 "BrightLux", "PrecisionSeal", "GlobalHydraulics", "ProCoat"]
    plants = ["Plant A - North", "Plant B - South", "Plant C - East", "Plant D - West"]
    parts = ["BRG-4421", "HYD-7834", "FLT-3302", "LED-9917", "STL-1100",
             "EXH-5543", "TRN-6620", "GSK-0034", "WDW-2240"]

    quantities = np.random.randint(50, 5000, size=n)
    unit_costs = np.round(np.random.uniform(5, 500, size=n), 2)

    df = pd.DataFrame({
        "po_number": [f"PO-2024-{i:04d}" for i in range(1, n + 1)],
        "supplier": [random.choice(suppliers) for _ in range(n)],
        "part_number": [random.choice(parts) for _ in range(n)],
        "qty_ordered": quantities,
        "unit_cost": unit_costs,
        "line_total": np.round(quantities * unit_costs, 2),
        "plant": [random.choice(plants) for _ in range(n)],
        "cost_center": [f"CC-{random.randint(4000,4050)}" for _ in range(n)],
        "order_date": pd.date_range(end=datetime.now(), periods=n, freq="2D").strftime("%Y-%m-%d").tolist(),
        "inspection_status": [random.choice(["accepted", "rejected", "pending", "on_hold"]) for _ in range(n)],
    })

    n_issues = int(n * noise_level)

    for _ in range(int(n_issues * 0.4)):
        col = random.choice(["supplier", "unit_cost", "line_total", "cost_center"])
        row = random.randint(0, n - 1)
        df.loc[row, col] = None

    for _ in range(int(n_issues * 0.2)):
        row = random.randint(0, n - 1)
        if random.random() > 0.5:
            df.loc[row, "qty_ordered"] = random.randint(-100, -1)
        else:
            df.loc[row, "line_total"] = round(random.uniform(-50000, -1000), 2)

    for _ in range(int(n_issues * 0.15)):
        col = random.choice(["supplier", "plant"])
        row = random.randint(0, n - 1)
        val = df.loc[row, col]
        if isinstance(val, str):
            df.loc[row, col] = f" {val} "

    for _ in range(int(n_issues * 0.05)):
        src = random.randint(0, n - 1)
        df = pd.concat([df, df.iloc[[src]]], ignore_index=True)

    df = inject_common_issues(df, noise_level,
                               text_cols=["supplier", "part_number", "plant", "cost_center"],
                               date_cols=["order_date"])
    return df

# Customer CRM data with realistic distributions and quality issues.
def generate_customer_data(noise_level=0.1):
    n = random.randint(80, 160)
    statuses = ["active", "inactive", "pending", "churned"]

    df = pd.DataFrame({
        "customer_id": [f"CUST-{i:05d}" for i in range(1, n + 1)],
        "customer_name": [f"Customer {i}" for i in range(1, n + 1)],
        "email": [f"customer{i}@email.com" for i in range(1, n + 1)],
        "age": np.random.randint(18, 75, size=n).astype(float),
        "account_balance": np.round(np.random.uniform(-500, 25000, size=n), 2),
        "credit_score": np.random.randint(300, 850, size=n),
        "signup_date": pd.date_range(end=datetime.now(), periods=n, freq="7D").strftime("%Y-%m-%d").tolist(),
        "last_login": pd.date_range(end=datetime.now(), periods=n, freq="1D").strftime("%Y-%m-%d %H:%M:%S").tolist(),
        "status": [random.choice(statuses) for _ in range(n)],
    })

    n_issues = int(n * noise_level)

    for _ in range(int(n_issues * 0.4)):
        col = random.choice(["customer_name", "email", "age", "last_login"])
        row = random.randint(0, n - 1)
        df.loc[row, col] = None

    for _ in range(int(n_issues * 0.25)):
        row = random.randint(0, n - 1)
        if random.random() > 0.5:
            df.loc[row, "age"] = random.choice([-5, -2, 135, 150, 200])
        else:
            df.loc[row, "account_balance"] = round(random.uniform(-10000, -1000), 2)

    for _ in range(int(n_issues * 0.15)):
        col = random.choice(["customer_name", "email"])
        row = random.randint(0, n - 1)
        val = df.loc[row, col]
        if isinstance(val, str):
            df.loc[row, col] = f"  {val}"

    for _ in range(int(n_issues * 0.03)):
        src = random.randint(0, n - 1)
        df = pd.concat([df, df.iloc[[src]]], ignore_index=True)

    df = inject_common_issues(df, noise_level,
                               text_cols=["customer_name", "email", "status"],
                               date_cols=["signup_date", "last_login"])
    return df

    return df


# ---- Config for each source ----

SOURCE_CONFIGS = {
    "hr_system": {
        "generator": generate_hr_data,
        "config": {
            "data_source": "hr_system",
            "ranges": {"age": (0, 120), "salary": (0, 300000), "rating": (0, 5)},
        },
    },
    "factory_iot": {
        "generator": generate_sensor_data,
        "config": {
            "data_source": "factory_iot",
            "ranges": {"temperature": (-50, 150), "humidity": (0, 100)},
        },
    },
    "erp_export": {
        "generator": generate_procurement_data,
        "config": {
            "data_source": "erp_export",
            "ranges": {"quantity": (0, None), "price": (0, None)},
        },
    },
    "customer_data": {
        "generator": generate_customer_data,
        "config": {
            "data_source": "customer_data",
            "ranges": {"age": (0, 120)},
        },
    },
}

# Each generator creates a realistic dataset for that domain, then injects quality issues based on the noise_level parameter.
def generate_history(runs_per_source=30, start_date=None, end_date=None):
    if start_date is None:
        start_date = datetime.now() - timedelta(days=120)
    if end_date is None:
        end_date = datetime.now()

    total_days = (end_date - start_date).days
    engine = QualityEngine()
    total_runs = runs_per_source * len(SOURCE_CONFIGS)

    print(f"Generating {total_runs} historical runs ({runs_per_source} per source)...")
    print(f"Date range: {start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')} ({total_days} days)")
    print()

    run_count = 0
    for source_name, source_info in SOURCE_CONFIGS.items():
        generator = source_info["generator"]
        config = source_info["config"]

        print(f"  {source_name}: ", end="", flush=True)

        for i in range(runs_per_source):
            # noise decreases over time (quality improves) with some randomness
            progress = i / runs_per_source  # 0.0 to 1.0
            base_noise = 0.25 - (progress * 0.15)  # starts ~0.25, drops to ~0.10
            noise = max(0.02, base_noise + random.uniform(-0.05, 0.05))

            # generate data with this noise level
            df = generator(noise_level=noise)

            # save temp file
            temp_file = f"_temp_{source_name}.json"
            df.to_json(temp_file, orient="records", indent=2)

            try:
                # run through the actual engine
                report = engine.run(
                    filepath=temp_file,
                    config_path=None,
                    parallel=True,
                )

                # update the run timestamp in the database to simulate historical dates
                run_date = start_date + timedelta(days=(total_days * i / runs_per_source))
                import sqlite3
                conn = sqlite3.connect("db/quality_results.db")
                conn.execute(
                    "UPDATE runs SET run_timestamp = ?, data_source = ?, file_name = ? WHERE run_id = ?",
                    (run_date.isoformat(), source_name, f"{source_name}.json", report["run_id"])
                )
                conn.commit()
                conn.close()

                run_count += 1
                print(".", end="", flush=True)

            except Exception as e:
                print(f"X({e})", end="", flush=True)
            finally:
                if os.path.exists(temp_file):
                    os.remove(temp_file)

        print(f" done ({runs_per_source} runs)")

    print(f"\nTotal runs generated: {run_count}")
    print(f"Database: db/quality_results.db")

    # show summary
    import sqlite3
    conn = sqlite3.connect("db/quality_results.db")
    cursor = conn.cursor()

    cursor.execute("SELECT data_source, COUNT(*), ROUND(AVG(overall_score),2), MIN(grade), MAX(grade) FROM runs GROUP BY data_source")
    print(f"\n{'Source':<20} {'Runs':<8} {'Avg Score':<12} {'Grade Range'}")
    print("-" * 55)
    for row in cursor.fetchall():
        print(f"{row[0]:<20} {row[1]:<8} {row[2]:<12} {row[3]} - {row[4]}")

    cursor.execute("SELECT COUNT(*) FROM flagged_records")
    flagged_count = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM column_profiles")
    profile_count = cursor.fetchone()[0]
    print(f"\nFlagged records stored: {flagged_count:,}")
    print(f"Column profiles stored: {profile_count:,}")
    conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Generate historical quality check data",
        epilog="""
Examples:
  python generate_history.py --start 2025-11-01 --end 2026-04-02
  python generate_history.py --start 2025-11-01 --end 2026-04-02 --runs 50
  python generate_history.py --start 2025-11-01 --end 2026-04-02 --clean
  python generate_history.py --runs 20   (uses default: 120 days back to today)
        """,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--runs", type=int, default=30, help="Runs per data source (default: 30)")
    parser.add_argument("--start", type=str, default=None, help="Start date YYYY-MM-DD (default: 120 days ago)")
    parser.add_argument("--end", type=str, default=None, help="End date YYYY-MM-DD (default: today)")
    parser.add_argument("--clean", action="store_true", help="Delete existing database first")
    args = parser.parse_args()

    if args.clean and os.path.exists("db/quality_results.db"):
        os.remove("db/quality_results.db")
        print("Cleaned existing database.\n")

    start = datetime.strptime(args.start, "%Y-%m-%d") if args.start else datetime.now() - timedelta(days=120)
    end = datetime.strptime(args.end, "%Y-%m-%d") if args.end else datetime.now()

    generate_history(runs_per_source=args.runs, start_date=start, end_date=end)
