# KPI Scorer - Computes overall data quality score and grade from check results.
# Uses weighted dimensions (completeness, uniqueness, validity, etc.) to calculate a final score and grade.

import pandas as pd
from checks.base_check import CheckResult


class KPIScorer:
    """
    Computes data quality KPIs from check results.

    Dimensions:
        - Completeness (30%): How much data is present
        - Uniqueness (20%): Duplicate rows
        - ID Uniqueness (20%): Duplicate IDs
        - Validity (20%): Values within expected ranges
        - Consistency (10%): Data format consistency

    Weights are configurable via config.
    """

    DEFAULT_WEIGHTS = {
        "completeness": 0.30,
        "uniqueness": 0.20,
        "id_uniqueness": 0.20,
        "validity": 0.20,
        "consistency": 0.10,
    }

    GRADE_THRESHOLDS = [
        (95, "A", "Excellent"),
        (85, "B", "Good"),
        (75, "C", "Fair"),
        (60, "D", "Poor"),
        (0,  "F", "Critical Issues"),
    ]

    def __init__(self, weights: dict = None):
        self.weights = weights or self.DEFAULT_WEIGHTS

    # --- Main method to compute score and grade from check results ---
    # Returns a dict with overall score, grade, and dimension scores.
    
    def compute(self, df: pd.DataFrame, results: list[CheckResult]) -> dict:

        results_map = {r.check_name: r for r in results}

        # Completeness ---
        total_cells = len(df) * len(df.columns)
        null_cells = df.isnull().sum().sum()
        completeness = ((total_cells - null_cells) / total_cells) * 100 if total_cells > 0 else 100

        # Uniqueness (duplicate rows) ---
        dup_result = results_map.get("duplicate_rows")
        dup_pct = dup_result.issue_percentage if dup_result else 0
        uniqueness = 100 - dup_pct

        # ID Uniqueness ---
        id_result = results_map.get("duplicate_ids")
        if id_result and id_result.total_checked > 0:
            id_uniqueness = 100 - id_result.issue_percentage
        else:
            id_uniqueness = 100.0

        # Validity (negatives + range issues) ---
        validity_penalties = 0
        for name in ["negative_values", "range_validation"]:
            r = results_map.get(name)
            if r and not r.passed:
                validity_penalties += 1
        validity = max(0, 100 - (validity_penalties * 10))

        # Consistency (whitespace + empty strings) ---
        consistency_penalties = 0
        for name in ["whitespace_issues", "empty_strings"]:
            r = results_map.get(name)
            if r and not r.passed:
                consistency_penalties += 1
        consistency = max(0, 100 - (consistency_penalties * 10))

        # Overall weighted score ---
        overall = (
            completeness * self.weights["completeness"]
            + uniqueness * self.weights["uniqueness"]
            + id_uniqueness * self.weights["id_uniqueness"]
            + validity * self.weights["validity"]
            + consistency * self.weights["consistency"]
        )

        # Grade ---
        grade_letter, grade_desc = "F", "Critical Issues"
        for threshold, letter, desc in self.GRADE_THRESHOLDS:
            if overall >= threshold:
                grade_letter, grade_desc = letter, desc
                break

        #Count total issues ---
        total_issues = sum(
            1 for r in results
            if not r.passed and r.category != "profiling"
        )

        return {
            "overall_score": float(round(overall, 2)),
            "grade": f"{grade_letter} ({grade_desc})",
            "dimensions": {
                "completeness": float(round(completeness, 2)),
                "uniqueness": float(round(uniqueness, 2)),
                "id_uniqueness": float(round(id_uniqueness, 2)),
                "validity": float(round(validity, 2)),
                "consistency": float(round(consistency, 2)),
            },
            "total_issues": int(total_issues),
        }
