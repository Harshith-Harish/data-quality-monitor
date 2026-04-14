"""Base class for quality checks. Inherit from this, implement execute()."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Any
import pandas as pd
 
 
@dataclass
class FlaggedRecord:
    # Represents a single record that failed a check, with context for debugging and ML.
    row_index: int
    primary_key: dict          # {"employee_id": "E008"}
    column: str
    value: Any                 # actual value found
    rule: str                  # "below_min", "duplicate", "missing", etc.
    expected: str              # "0-120", "not null", "unique"
    severity: str              # "critical", "high", "medium", "low"
    action_type: str           # "fix", "review", "delete", "investigate"
    context: dict = field(default_factory=dict)   # other columns for reference
    deviation: float = None    # std deviations from mean (for ML)
 
 
@dataclass
class ColumnProfile:
    # Summary statistics for a column, used for checks and ML features.
    column_name: str
    dtype: str
    total_count: int
    null_count: int
    unique_count: int
    mean: float = None
    std: float = None
    min_val: float = None
    max_val: float = None
    top_values: list = field(default_factory=list)  # most frequent for categoricals
 
 
@dataclass
class CheckResult:
    # Standardized result object for all checks, making it easy to log, report, and feed into ML models.
    check_name: str
    passed: bool
    issue_count: int = 0
    total_checked: int = 0
    details: list = field(default_factory=list)
    severity: str = "medium"
    category: str = "general"
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    flagged_records: list = field(default_factory=list)  # list of FlaggedRecord
    recommendation: str = ""
    action_type: str = "review"  # default action for this check
 
    @property
    def issue_percentage(self):
        if self.total_checked == 0:
            return 0.0
        return (self.issue_count / self.total_checked) * 100
 
    def summary(self):
        status = "PASS" if self.passed else "FAIL"
        return (
            f"[{status}] {self.check_name} | "
            f"Issues: {self.issue_count}/{self.total_checked} "
            f"({self.issue_percentage:.1f}%) | "
            f"Severity: {self.severity}"
        )
 
 
class BaseCheck(ABC):
    # All checks inherit from this and implement execute()
 
    name: str = "base_check"
    description: str = "Base quality check"
    category: str = "general"     # completeness, uniqueness, validity, consistency
    severity: str = "medium"      # low, medium, high, critical
 
    def __init__(self, config: Optional[dict] = None):
        """
        Args:
            config: Optional dict of check-specific configuration.
                    Loaded from YAML config files per data source.
        """
        self.config = config or {}
 
    @abstractmethod
    def execute(self, df: pd.DataFrame) -> CheckResult:
        """What a check returns after running."""
        pass
 
    def _make_result(self, passed: bool, issue_count: int,
                     total_checked: int, details: list,
                     flagged_records: list = None,
                     recommendation: str = "",
                     action_type: str = "review") -> CheckResult:
        """Helper to build a CheckResult with this check's metadata."""
        return CheckResult(
            check_name=self.name,
            passed=passed,
            issue_count=issue_count,
            total_checked=total_checked,
            details=details,
            severity=self.severity,
            category=self.category,
            flagged_records=flagged_records or [],
            recommendation=recommendation,
            action_type=action_type,
        )