# Concrete implementations of all data quality checks.
# each class is a pluggable strategy that inherits from BaseCheck.
# All checks now capture row-level flagged records with primary key references.


import pandas as pd
import numpy as np
from .base_check import BaseCheck, FlaggedRecord

MAX_FLAGS = 100  # cap per check to prevent database bloat


def _get_pk(row, pk_col):
    """Build primary key dict for a row."""
    if pk_col:
        val = row.get(pk_col)
        if isinstance(val, (np.integer,)):
            val = int(val)
        return {pk_col: val}
    return {"row_index": int(row.name)}


def _get_context(row, pk_col, flagged_col, context_cols):
    """Build context dict with limited columns for efficiency."""
    ctx = {}
    for c in [c for c in context_cols if c != flagged_col][:5]:
        val = row.get(c)
        if isinstance(val, (np.integer,)):
            val = int(val)
        elif isinstance(val, (np.floating,)):
            val = float(val)
        elif pd.isna(val):
            val = None
        ctx[c] = val
    return ctx


def _safe_val(val):
    """Convert numpy types to python types for JSON serialization."""
    if isinstance(val, (np.integer,)):
        return int(val)
    elif isinstance(val, (np.floating,)):
        return float(val)
    elif pd.isna(val):
        return None
    return val


def _deviation(value, mean, std):
    """How many std deviations from mean (for ML)."""
    if std and std > 0 and value is not None and not pd.isna(value):
        return round(abs(value - mean) / std, 2)
    return None


def _flag_rows(df, mask, col, pk_col, context_cols, rule, expected, severity, action_type, existing_flags, col_mean=None, col_std=None):
    """Common helper to flag rows matching a boolean mask."""
    flagged = []
    remaining = MAX_FLAGS - len(existing_flags)
    if remaining <= 0:
        return flagged
    for idx in df[mask].index[:remaining]:
        row = df.loc[idx]
        val = _safe_val(row[col]) if col in df.columns else None
        flagged.append(FlaggedRecord(
            row_index=int(idx),
            primary_key=_get_pk(row, pk_col),
            column=col,
            value=val,
            rule=rule,
            expected=expected,
            severity=severity,
            action_type=action_type,
            context=_get_context(row, pk_col, col, context_cols),
            deviation=_deviation(val, col_mean, col_std) if col_mean is not None else None,
        ))
    return flagged


class MissingValuesCheck(BaseCheck):
    name = "missing_values"
    description = "Detects null or missing values across all columns"
    category = "completeness"
    severity = "high"

    def execute(self, df, pk_col=None, context_cols=None):
        context_cols = context_cols or list(df.columns[:6])
        details, flagged, total_issues = [], [], 0
        total_cells = len(df) * len(df.columns)

        for col in df.columns:
            mask = df[col].isnull()
            count = mask.sum()
            if count > 0:
                details.append(f"{col}: {count} missing ({(count/len(df))*100:.1f}%)")
                total_issues += count
                flagged += _flag_rows(df, mask, col, pk_col, context_cols, "missing", "not null", self.severity, "fix", flagged)

        rec = ""
        if total_issues > 0:
            pct = (total_issues / total_cells) * 100
            if pct > 20:
                rec = "High missing rate. Investigate data pipeline or source system for systematic gaps."
            elif pct > 5:
                rec = "Moderate missing values. Consider imputation or flagging for manual review."
            else:
                rec = "Low missing rate. Review individual records for case-by-case fixes."

        return self._make_result(passed=(total_issues == 0), issue_count=total_issues, total_checked=total_cells,
                                 details=details or ["No missing values found"], flagged_records=flagged, recommendation=rec, action_type="fix")


class DuplicateRowsCheck(BaseCheck):
    name = "duplicate_rows"
    description = "Detects fully duplicated rows in the dataset"
    category = "uniqueness"
    severity = "high"

    def execute(self, df, pk_col=None, context_cols=None):
        context_cols = context_cols or list(df.columns[:6])
        mask = df.duplicated(keep="first")
        count = mask.sum()
        details, flagged = [], []

        if count > 0:
            details.append(f"Found {count} duplicate rows ({(count/len(df))*100:.1f}%)")
            for idx in df[mask].index[:MAX_FLAGS]:
                row = df.loc[idx]
                flagged.append(FlaggedRecord(
                    row_index=int(idx), primary_key=_get_pk(row, pk_col), column="(entire row)",
                    value="duplicate of earlier row", rule="duplicate_row", expected="unique row",
                    severity=self.severity, action_type="delete",
                    context=_get_context(row, pk_col, "", context_cols),
                ))
        else:
            details.append("No duplicate rows found")

        rec = "Remove duplicate rows. Check ETL pipeline for double-loading." if count > 0 else ""
        return self._make_result(passed=(count == 0), issue_count=count, total_checked=len(df),
                                 details=details, flagged_records=flagged, recommendation=rec, action_type="delete")


class DuplicateIDCheck(BaseCheck):
    name = "duplicate_ids"
    description = "Detects duplicate values in primary key and ID columns"
    category = "uniqueness"
    severity = "critical"

    # stricter pattern: matches columns like 'id', 'employee_id', 'id_number', 'record_id'
    # but NOT 'humidity', 'valid', 'android', 'ividend'
    ID_PATTERN = r'(^id$|^id_|_id$|_id_|_id\d)'

    def execute(self, df, pk_col=None, context_cols=None):
        import re
        context_cols = context_cols or list(df.columns[:6])
        details, flagged, total_issues = [], [], 0

        # if primary key is configured, check that first (always)
        id_cols = []
        if pk_col and pk_col in df.columns:
            id_cols.append(pk_col)

        # then find other ID columns using strict regex (exclude the pk_col to avoid double-checking)
        for col in df.columns:
            if col == pk_col:
                continue
            if re.search(self.ID_PATTERN, col.lower()):
                id_cols.append(col)

        for col in id_cols:
            mask = df[col].duplicated(keep="first")
            count = mask.sum()
            if count > 0:
                label = "(primary key)" if col == pk_col else ""
                details.append(f"{col} {label}: {count} duplicate values (should be unique!)")
                total_issues += count
                flagged += _flag_rows(df, mask, col, pk_col, context_cols, "duplicate_id", "unique", self.severity, "investigate", flagged)

        if not id_cols:
            details.append("No ID columns found")
        elif total_issues == 0:
            details.append("No duplicate IDs found")

        rec = "Critical: Duplicate primary keys break data integrity. Investigate source system." if total_issues > 0 else ""
        return self._make_result(passed=(total_issues == 0), issue_count=total_issues,
                                 total_checked=len(df) * len(id_cols) if id_cols else 0,
                                 details=details, flagged_records=flagged, recommendation=rec, action_type="investigate")


class EmptyStringsCheck(BaseCheck):
    name = "empty_strings"
    description = "Detects empty strings in text/object columns"
    category = "completeness"
    severity = "medium"

    def execute(self, df, pk_col=None, context_cols=None):
        context_cols = context_cols or list(df.columns[:6])
        details, flagged, total_issues = [], [], 0
        text_cols = df.select_dtypes(include=["object", "string"]).columns

        for col in text_cols:
            mask = (df[col] == "")
            count = mask.sum()
            if count > 0:
                details.append(f"{col}: {count} empty strings")
                total_issues += count
                flagged += _flag_rows(df, mask, col, pk_col, context_cols, "empty_string", "non-empty value", self.severity, "fix", flagged)

        if total_issues == 0:
            details.append("No empty strings found")

        rec = "Empty strings differ from nulls and can cause silent failures. Replace with null or valid values." if total_issues > 0 else ""
        return self._make_result(passed=(total_issues == 0), issue_count=total_issues,
                                 total_checked=len(df) * len(text_cols) if len(text_cols) > 0 else 0,
                                 details=details, flagged_records=flagged, recommendation=rec, action_type="fix")


class WhitespaceCheck(BaseCheck):
    name = "whitespace_issues"
    description = "Detects extra leading/trailing spaces in text columns"
    category = "consistency"
    severity = "low"

    def execute(self, df, pk_col=None, context_cols=None):
        context_cols = context_cols or list(df.columns[:6])
        details, flagged, total_issues = [], [], 0
        text_cols = df.select_dtypes(include=["object", "string"]).columns

        for col in text_cols:
            mask = (df[col].astype(str).str.strip() != df[col].astype(str))
            count = mask.sum()
            if count > 0:
                details.append(f"{col}: {count} values with extra spaces")
                total_issues += count
                remaining = MAX_FLAGS - len(flagged)
                if remaining > 0:
                    for idx in df[mask].index[:remaining]:
                        row = df.loc[idx]
                        val = row[col]
                        flagged.append(FlaggedRecord(
                            row_index=int(idx), primary_key=_get_pk(row, pk_col), column=col,
                            value=repr(val), rule="whitespace", expected=f"'{str(val).strip()}'",
                            severity=self.severity, action_type="fix",
                            context=_get_context(row, pk_col, col, context_cols),
                        ))

        if total_issues == 0:
            details.append("No whitespace issues found")

        rec = "Apply .strip() to affected columns. Whitespace causes join failures and lookup mismatches." if total_issues > 0 else ""
        return self._make_result(passed=(total_issues == 0), issue_count=total_issues,
                                 total_checked=len(df) * len(text_cols) if len(text_cols) > 0 else 0,
                                 details=details, flagged_records=flagged, recommendation=rec, action_type="fix")


class NegativeValuesCheck(BaseCheck):
    name = "negative_values"
    description = "Detects negative values in numeric columns"
    category = "validity"
    severity = "medium"

    def execute(self, df, pk_col=None, context_cols=None):
        context_cols = context_cols or list(df.columns[:6])
        details, flagged, total_issues = [], [], 0
        numeric_cols = df.select_dtypes(include=["int64", "float64"]).columns

        for col in numeric_cols:
            mask = (df[col] < 0)
            count = mask.sum()
            if count > 0:
                details.append(f"{col}: {count} negative values")
                total_issues += count
                flagged += _flag_rows(df, mask, col, pk_col, context_cols, "negative", ">= 0",
                                      self.severity, "review", flagged, df[col].mean(), df[col].std())

        if total_issues == 0:
            details.append("No negative values found")

        rec = "Review negative values. Could be data entry errors, refunds/reversals, or sign convention issues." if total_issues > 0 else ""
        return self._make_result(passed=(total_issues == 0), issue_count=total_issues,
                                 total_checked=len(df) * len(numeric_cols) if len(numeric_cols) > 0 else 0,
                                 details=details, flagged_records=flagged, recommendation=rec, action_type="review")


class RangeValidationCheck(BaseCheck):
    name = "range_validation"
    description = "Validates numeric values fall within expected ranges"
    category = "validity"
    severity = "high"

    DEFAULT_RANGES = {
        "age": (0, 120), "salary": (0, 1_000_000), "temperature": (-50, 150),
        "humidity": (0, 100), "price": (0, None), "quantity": (0, None),
        "percentage": (0, 100), "rating": (0, 5),
    }

    def execute(self, df, pk_col=None, context_cols=None):
        context_cols = context_cols or list(df.columns[:6])
        details, flagged, total_issues = [], [], 0

        ranges = {**self.DEFAULT_RANGES}
        if "ranges" in self.config:
            ranges.update(self.config["ranges"])

        numeric_cols = df.select_dtypes(include=["int64", "float64"]).columns

        for col in numeric_cols:
            col_mean, col_std = df[col].mean(), df[col].std()
            for key, (min_val, max_val) in ranges.items():
                if key in col.lower():
                    if min_val is not None:
                        mask = (df[col] < min_val)
                        below = mask.sum()
                        if below > 0:
                            details.append(f"{col}: {below} values below min ({min_val})")
                            total_issues += below
                            flagged += _flag_rows(df, mask, col, pk_col, context_cols, "below_min",
                                                  f">= {min_val}", self.severity, "fix", flagged, col_mean, col_std)
                    if max_val is not None:
                        mask = (df[col] > max_val)
                        above = mask.sum()
                        if above > 0:
                            details.append(f"{col}: {above} values above max ({max_val})")
                            total_issues += above
                            flagged += _flag_rows(df, mask, col, pk_col, context_cols, "above_max",
                                                  f"<= {max_val}", self.severity, "fix", flagged, col_mean, col_std)
                    break

        if total_issues == 0:
            details.append("No range issues found (or no matching columns)")

        rec = "Values outside expected ranges. Verify against business rules or adjust range config." if total_issues > 0 else ""
        return self._make_result(passed=(total_issues == 0), issue_count=total_issues,
                                 total_checked=len(df) * len(numeric_cols) if len(numeric_cols) > 0 else 0,
                                 details=details, flagged_records=flagged, recommendation=rec, action_type="fix")


class TimestampCheck(BaseCheck):
    name = "timestamp_check"
    description = "Validates timestamps for ordering, future dates, and gaps"
    category = "consistency"
    severity = "medium"

    def execute(self, df, pk_col=None, context_cols=None):
        context_cols = context_cols or list(df.columns[:6])
        details, flagged, total_issues = [], [], 0

        # engine already converted datetime columns, so just pick them up
        date_cols = df.select_dtypes(include=["datetime64", "datetime64[ns]"]).columns.tolist()
        if not date_cols:
            return self._make_result(passed=True, issue_count=0, total_checked=0, details=["No date/timestamp columns found"])

        for col in date_cols:
            null_mask = df[col].isnull()
            null_dates = null_mask.sum()
            if null_dates > 0:
                details.append(f"{col}: {null_dates} invalid/missing timestamps")
                total_issues += null_dates
                remaining = MAX_FLAGS - len(flagged)
                if remaining > 0:
                    for idx in df[null_mask].index[:remaining]:
                        row = df.loc[idx]
                        flagged.append(FlaggedRecord(
                            row_index=int(idx), primary_key=_get_pk(row, pk_col), column=col,
                            value=None, rule="missing_timestamp", expected="valid date",
                            severity=self.severity, action_type="fix",
                            context=_get_context(row, pk_col, col, context_cols),
                        ))

            if not df[col].isnull().all():
                if not df[col].dropna().is_monotonic_increasing:
                    details.append(f"{col}: Timestamps not in chronological order")
                    total_issues += 1

                future_mask = (df[col] > pd.Timestamp.now())
                future = future_mask.sum()
                if future > 0:
                    details.append(f"{col}: {future} future dates found")
                    total_issues += future
                    remaining = MAX_FLAGS - len(flagged)
                    if remaining > 0:
                        for idx in df[future_mask].index[:remaining]:
                            row = df.loc[idx]
                            flagged.append(FlaggedRecord(
                                row_index=int(idx), primary_key=_get_pk(row, pk_col), column=col,
                                value=str(df.loc[idx, col]), rule="future_date", expected="<= current date",
                                severity="high", action_type="investigate",
                                context=_get_context(row, pk_col, col, context_cols),
                            ))

                if len(df) > 1:
                    diffs = df[col].diff().dropna()
                    details.append(f"{col}: Average gap = {diffs.mean()}")
                    details.append(f"{col}: Max gap = {diffs.max()}")

        rec = "Timestamp issues can break time-series analysis. Check for timezone, clock errors, or data entry mistakes." if total_issues > 0 else ""
        return self._make_result(passed=(total_issues == 0), issue_count=total_issues, total_checked=len(df) * len(date_cols),
                                 details=details, flagged_records=flagged, recommendation=rec, action_type="investigate")


class StatisticsCheck(BaseCheck):
    name = "statistics"
    description = "Computes basic stats (min, max, mean, std) for numeric columns"
    category = "profiling"
    severity = "low"

    def execute(self, df, pk_col=None, context_cols=None):
        details = []
        numeric_cols = df.select_dtypes(include=["int64", "float64"]).columns
        if len(numeric_cols) == 0:
            details.append("No numeric columns")
        else:
            for col in numeric_cols:
                details.append(f"{col}: min={df[col].min()}, max={df[col].max()}, avg={df[col].mean():.2f}, std={df[col].std():.2f}")
        return self._make_result(passed=True, issue_count=0,
                                 total_checked=len(df) * len(numeric_cols) if len(numeric_cols) > 0 else 0, details=details)


class DataTypesCheck(BaseCheck):
    name = "data_types"
    description = "Reports the data type of each column"
    category = "profiling"
    severity = "low"

    def execute(self, df, pk_col=None, context_cols=None):
        details = [f"{col}: {df[col].dtype}" for col in df.columns]
        return self._make_result(passed=True, issue_count=0, total_checked=len(df.columns), details=details)