# keeps track of available checks, registers new ones automatically
from .base_check import BaseCheck
from .all_checks import (
    MissingValuesCheck,
    DuplicateRowsCheck,
    DuplicateIDCheck,
    EmptyStringsCheck,
    WhitespaceCheck,
    NegativeValuesCheck,
    RangeValidationCheck,
    TimestampCheck,
    StatisticsCheck,
    DataTypesCheck,
)
 

class CheckRegistry:
    BUILT_IN_CHECKS = [
        MissingValuesCheck,
        DuplicateRowsCheck,
        DuplicateIDCheck,
        EmptyStringsCheck,
        WhitespaceCheck,
        NegativeValuesCheck,
        RangeValidationCheck,
        TimestampCheck,
        StatisticsCheck,
        DataTypesCheck,
    ]

    def __init__(self):
        self._checks = {}
        # register all the built-in ones on startup
        for cls in self.BUILT_IN_CHECKS:
            self.register(cls)

    def register(self, check_cls):
        # Adds a check class to the registry
        if not issubclass(check_cls, BaseCheck):
            raise TypeError(f"{check_cls.__name__} must inherit from BaseCheck")
        self._checks[check_cls.name] = check_cls

    def get_all(self):
        return dict(self._checks)

    def get_by_category(self, category):
        return {
            name: cls for name, cls in self._checks.items() if cls.category == category
        }

    def get_by_name(self, name):
        if name not in self._checks:
            raise KeyError(
                f"Check '{name}' not found. Available: {list(self._checks.keys())}"
            )
        return self._checks[name]

    def list_checks(self):
        # handy for debugging - shows whats registered
        return [
            {"name": cls.name, "category": cls.category, "severity": cls.severity}
            for cls in self._checks.values()
        ]

    def unregister(self, name):
        self._checks.pop(name, None)
