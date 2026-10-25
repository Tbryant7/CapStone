"""Validation & Safety Engine (SDS 2.2).

* ``RangeTable``: the safe min/max for each parameter, loaded from
  ``validation/ranges.json``.
* ``ValidationEngine``: checks a program against those limits. Every path that
  loads or saves a program must go through it (REQ-16, REQ-17).
"""

from .engine import ValidationEngine, ValidationResult, validate_program
from .range_table import (
    DEFAULT_RANGES_PATH,
    REQUIRED_PARAMETERS,
    Limit,
    RangeTable,
    RangeTableError,
    load_or_exit_message,
)

__all__ = [
    "DEFAULT_RANGES_PATH",
    "REQUIRED_PARAMETERS",
    "Limit",
    "RangeTable",
    "RangeTableError",
    "ValidationEngine",
    "ValidationResult",
    "load_or_exit_message",
    "validate_program",
]
