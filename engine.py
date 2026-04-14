# Main engine that coordinates the full quality check pipeline:
#     1. Load data from any supported format
#     2. Load config (or use defaults - works without config)
#     3. Instantiate applicable checks from registry
#     4. Run checks (parallel or sequential)
#     5. Score results
#     6. Store to database
#     7. Generate report
# Designed to work with ANY tabular dataset without modification.

"""
Quality Engine - The orchestrator.
Loads data, runs checks (with parallel execution), scores results, and stores them.
Works with ANY tabular data - CSV, Excel, JSON.
"""

import os
import time
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional

import pandas as pd

from checks.base_check import BaseCheck, CheckResult, ColumnProfile
from checks.registry import CheckRegistry
from loader import DataLoader
from config_manager import ConfigManager
from scorer import KPIScorer
from result_store import ResultStore


class QualityEngine:

    def __init__(
        self,
        db_path: str = "db/quality_results.db",
        config_dir: str = "configs",
        max_workers: int = 4,
    ):
        self.registry = CheckRegistry()
        self.loader = DataLoader()
        self.config_manager = ConfigManager(config_dir=config_dir)
        self.scorer = KPIScorer()
        self.store = ResultStore(db_path=db_path)
        self.max_workers = max_workers

    def run(
        self,
        filepath: str,
        config_path: Optional[str] = None,
        parallel: bool = True,
    ) -> dict:
        """
        Execute a full quality check run on any data file.

        Args:
            filepath:    Path to CSV, Excel, or JSON file
            config_path: Optional YAML config for data-source-specific rules
            parallel:    Run checks in parallel (default True)

        Returns:
            dict with full report: score, grade, check results, metadata
        """
        run_start = time.time()

        # load file
        df = self.loader.load(filepath)
        file_name = os.path.basename(filepath)

        # fix date columns early so all checks see correct types
        df = self._detect_datetime_columns(df)

        # load config if provided
        config = self.config_manager.load(config_path)
        data_source = config.get("data_source", file_name)

        if "weights" in config:
            self.scorer = KPIScorer(weights=config["weights"])

        # figure out which column is the PK
        pk_col = self._detect_primary_key(df, config)
        context_cols = config.get("context_columns", list(df.columns[:6])) #defaults to the first 6 columns 

        # profile columns for ML later
        profiles = self._build_column_profiles(df) 

        # which checks to run
        checks = self._resolve_checks(config)

        # run checks
        if parallel and len(checks) > 1:
            results = self._run_parallel(checks, df, pk_col, context_cols)
        else:
            results = self._run_sequential(checks, df, pk_col, context_cols)

        # scoring it
        kpi = self.scorer.compute(df, results)

        # save to db
        run_id = self.store.save_run(
            file_name=file_name,
            data_source=data_source,
            row_count=len(df),
            column_count=len(df.columns),
            overall_score=kpi["overall_score"],
            grade=kpi["grade"],
            total_issues=int(kpi["total_issues"]),
            results=results,
            profiles=profiles,
        )

        elapsed = time.time() - run_start

        # preview first few rows for the report
        preview_rows = df.head(5).fillna("(null)").to_dict(orient="records")

        # flatten all flagged records into one list
        all_flagged = []
        for r in results:
            for f in r.flagged_records:
                all_flagged.append({
                    "check": r.check_name,
                    "row_index": f.row_index,
                    "primary_key": f.primary_key,
                    "column": f.column,
                    "value": f.value,
                    "rule": f.rule,
                    "expected": f.expected,
                    "severity": f.severity,
                    "action_type": f.action_type,
                    "context": f.context,
                    "deviation": f.deviation,
                })

        # # build the report dict
        report = {
            "run_id": run_id,
            "file_name": file_name,
            "data_source": data_source,
            "timestamp": datetime.now().isoformat(),
            "rows": len(df),
            "columns": len(df.columns),
            "column_names": list(df.columns),
            "primary_key": pk_col,
            "checks_run": len(results),
            "execution_time_sec": round(elapsed, 3),
            "parallel": parallel,
            "preview": preview_rows,
            "kpi": kpi,
            "results": [
                {
                    "check_name": r.check_name,
                    "category": r.category,
                    "severity": r.severity,
                    "passed": r.passed,
                    "issue_count": r.issue_count,
                    "total_checked": r.total_checked,
                    "issue_pct": round(r.issue_percentage, 2),
                    "details": r.details,
                    "recommendation": r.recommendation,
                    "action_type": r.action_type,
                    "flagged_count": len(r.flagged_records),
                }
                for r in results
            ],
            "flagged_records": all_flagged,
            "profiles": [
                {
                    "column_name": p.column_name,
                    "dtype": p.dtype,
                    "total_count": p.total_count,
                    "null_count": p.null_count,
                    "unique_count": p.unique_count,
                    "mean": p.mean,
                    "std": p.std,
                    "min_val": p.min_val,
                    "max_val": p.max_val,
                    "top_values": p.top_values,
                }
                for p in profiles
            ],
        }

        return report

    def _resolve_checks(self, config: dict) -> list[BaseCheck]:
        """Figure out which checks to run based on config."""
        all_checks = self.registry.get_all()

        enabled = config.get("checks", {}).get("enabled", [])
        disabled = config.get("checks", {}).get("disabled", [])

        if enabled:
            # only run explicitly enabled checks
            check_classes = {
                name: cls for name, cls in all_checks.items()
                if name in enabled
            }
        else:
            # run all except disabled
            check_classes = {
                name: cls for name, cls in all_checks.items()
                if name not in disabled
            }

        # instantiate with config (so checks like RangeValidation get custom ranges)
        return [cls(config=config) for cls in check_classes.values()]

    def _run_sequential(self, checks: list[BaseCheck], df: pd.DataFrame,
                         pk_col=None, context_cols=None) -> list[CheckResult]:
        """Sequential execution - easier to debug."""
        results = []
        for check in checks:
            try:
                result = check.execute(df, pk_col=pk_col, context_cols=context_cols)
                results.append(result)
            except Exception as e:
                results.append(CheckResult(
                    check_name=check.name,
                    passed=False,
                    issue_count=0,
                    total_checked=0,
                    details=[f"CHECK ERROR: {str(e)}"],
                    severity="critical",
                    category=check.category,
                ))
        return results

    def _run_parallel(self, checks: list[BaseCheck], df: pd.DataFrame,
                       pk_col=None, context_cols=None) -> list[CheckResult]:
        """Parallel execution - each check gets its own thread."""
        results = []

        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            future_to_check = {
                executor.submit(self._safe_execute, check, df, pk_col, context_cols): check
                for check in checks
            }

            for future in as_completed(future_to_check):
                check = future_to_check[future]
                try:
                    result = future.result()
                    results.append(result)
                except Exception as e:
                    results.append(CheckResult(
                        check_name=check.name,
                        passed=False,
                        issue_count=0,
                        total_checked=0,
                        details=[f"PARALLEL EXECUTION ERROR: {str(e)}"],
                        severity="critical",
                        category=check.category,
                    ))

        results.sort(key=lambda r: r.check_name)
        return results

    def _safe_execute(self, check: BaseCheck, df: pd.DataFrame,
                       pk_col=None, context_cols=None) -> CheckResult:
        """Safe wrapper for threading."""
        return check.execute(df, pk_col=pk_col, context_cols=context_cols)

    def register_custom_check(self, check_cls: type):
        """Add a custom check to the registry."""
        self.registry.register(check_cls)

    def get_history(self, file_name: str = None, limit: int = 20) -> list[dict]:
        """Get historical run data for trend analysis."""
        return self.store.get_run_history(file_name=file_name, limit=limit)

    def get_trend(self, file_name: str, check_name: str = None) -> list[dict]:
        """Trend data for dashboards."""
        return self.store.get_trend_data(file_name, check_name)

    def _detect_datetime_columns(self, df: pd.DataFrame) -> pd.DataFrame:
        """Try converting string columns to datetime. Done once before checks run."""
        for col in df.select_dtypes(include=["object"]).columns:
            # skip columns that are mostly empty or short strings unlikely to be dates
            non_null = df[col].dropna()
            if len(non_null) == 0:
                continue
            try:
                converted = pd.to_datetime(non_null, errors="raise", format="mixed")
                df[col] = pd.to_datetime(df[col], errors="coerce", format="mixed")
            except (ValueError, TypeError):
                pass
        return df

    def _detect_primary_key(self, df: pd.DataFrame, config: dict) -> Optional[str]:
        """Find the best PK column. Config wins, then auto-detect by pattern + uniqueness."""
        import re
        ID_PATTERN = r'(^id$|^id_|_id$|_id_|_id\d)'

        # config takes priority
        if config.get("primary_key"):
            return config["primary_key"]

        # try to find an id-like column with unique values
        for col in df.columns:
            if re.search(ID_PATTERN, col.lower()) and df[col].nunique() == len(df):
                return col

        # any column with all unique values (first one)
        for col in df.columns:
            if df[col].nunique() == len(df):
                return col

        return None

    def _build_column_profiles(self, df: pd.DataFrame) -> list:
        """Column-level stats for profiling and ML features."""
        import numpy as np
        profiles = []
        for col in df.columns:
            profile = ColumnProfile(
                column_name=col,
                dtype=str(df[col].dtype),
                total_count=len(df),
                null_count=int(df[col].isnull().sum()),
                unique_count=int(df[col].nunique()),
            )

            if df[col].dtype in ["int64", "float64"]:
                profile.mean = round(float(df[col].mean()), 4) if not df[col].isnull().all() else None
                profile.std = round(float(df[col].std()), 4) if not df[col].isnull().all() else None
                profile.min_val = float(df[col].min()) if not df[col].isnull().all() else None
                profile.max_val = float(df[col].max()) if not df[col].isnull().all() else None
            elif df[col].dtype in ["object", "string"]:
                top = df[col].value_counts().head(5).to_dict()
                profile.top_values = [{"value": k, "count": int(v)} for k, v in top.items()]

            profiles.append(profile)
        return profiles

    def export_flagged_csv(self, report: dict, output_dir: str = "flagged_records"):
        """Dumping flagged records to CSV. Each run gets its own file."""
        if not report.get("flagged_records"):
            print("No flagged records to export.")
            return None

        os.makedirs(output_dir, exist_ok=True)

        from datetime import datetime as dt
        timestamp = dt.now().strftime("%Y%m%d_%H%M%S")
        run_id = report.get("run_id", 0)
        file_name = report.get("file_name", "unknown").replace(".", "_")
        output_path = os.path.join(
            output_dir,
            f"flagged_run{run_id}_{file_name}_{timestamp}.csv"
        )

        rows = []
        for f in report["flagged_records"]:
            row = {
                "run_id": run_id,
                "check": f["check"],
                "severity": f["severity"],
                "action_type": f["action_type"],
                "row_index": f["row_index"],
                "column": f["column"],
                "value": f["value"],
                "rule": f["rule"],
                "expected": f["expected"],
                "deviation": f["deviation"],
            }
            for k, v in f["primary_key"].items():
                row[f"pk_{k}"] = v
            for k, v in f["context"].items():
                row[f"ctx_{k}"] = v
            rows.append(row)

        export_df = pd.DataFrame(rows)
        severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        export_df["_sev_order"] = export_df["severity"].map(severity_order)
        export_df = export_df.sort_values("_sev_order").drop(columns=["_sev_order"])
        export_df.to_csv(output_path, index=False)
        return output_path