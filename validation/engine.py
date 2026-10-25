"""ValidationEngine: checks a program against the safe ranges (REQ-16, REQ-17).

Every path that loads or saves a program must call :meth:`ValidationEngine.validate`
and refuse to save or run a program whose result is not valid.

    engine = ValidationEngine()              # uses validation/ranges.json
    result = engine.validate(program)
    if not result.is_valid:
        for message in result.failed_parameters:
            print(message)   # "Channel 2 amplitude 40 mA is above the 3 mA limit"
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from files.program import Program

from .range_table import Limit, RangeTable

#: (attribute on Channel, parameter name in the RangeTable)
CHANNEL_PARAMETERS = (
    ("pulse_width_us", "pulse_width"),
    ("amplitude_ma", "amplitude"),
    ("frequency_hz", "frequency"),
)


@dataclass(frozen=True)
class ValidationResult:
    """Outcome of one validation.

    ``failed_parameters`` holds one plain-language message per problem, in
    the order found. It is empty exactly when ``is_valid`` is True.
    ``isValid`` / ``failedParameters`` are the same values under the names
    used in the SDS.
    """

    is_valid: bool
    failed_parameters: list[str] = field(default_factory=list)

    @property
    def isValid(self) -> bool:  # noqa: N802 (SDS name)
        return self.is_valid

    @property
    def failedParameters(self) -> list[str]:  # noqa: N802 (SDS name)
        return list(self.failed_parameters)

    def summary(self) -> str:
        """One line for a status label: "Passed" or "Failed: 2 problems"."""
        if self.is_valid:
            return "Passed"
        n = len(self.failed_parameters)
        return f"Failed: {n} problem{'s' if n != 1 else ''}"


class ValidationEngine:
    def __init__(self, range_table: RangeTable | None = None) -> None:
        self.ranges = range_table if range_table is not None else RangeTable.load()

    def validate(self, program: Program | None) -> ValidationResult:
        problems: list[str] = []

        if program is None:
            return ValidationResult(False, ["No program to check."])
        if not isinstance(program, Program):
            return ValidationResult(False, ["This is not a stimulation program."])

        self._check_value("Time step", program.time_step_ms, self.ranges["time_step"], problems)

        if not program.channels:
            problems.append("Program has no channels. Add at least one channel.")

        seen: set[int] = set()
        for index, channel in enumerate(program.channels, start=1):
            number = channel.number
            if _is_int(number) and number >= 1:
                number = int(number)
                name = f"Channel {number}"
                if number in seen:
                    problems.append(f"{name} appears more than once.")
                seen.add(number)
            else:
                name = f"Channel entry {index}"
                if number is None:
                    problems.append(f"{name} has no channel number.")
                else:
                    problems.append(
                        f"{name} has an invalid channel number {number!r} "
                        "(must be a whole number, 1 or more)."
                    )

            for attribute, parameter in CHANNEL_PARAMETERS:
                limit = self.ranges[parameter]
                self._check_value(f"{name} {limit.label}", getattr(channel, attribute), limit, problems)

        return ValidationResult(not problems, problems)

    # ------------------------------------------------------------ helpers

    @staticmethod
    def _check_value(what: str, value: Any, limit: Limit, problems: list[str]) -> None:
        if value is None:
            problems.append(f"{what} is missing.")
        elif not _is_number(value):
            problems.append(f"{what} {value!r} is not a number.")
        elif value < limit.min:
            problems.append(
                f"{what} {_fmt(value, limit)} is below the {_fmt(limit.min, limit)} minimum."
            )
        elif value > limit.max:
            problems.append(
                f"{what} {_fmt(value, limit)} is above the {_fmt(limit.max, limit)} limit."
            )


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _is_int(value: Any) -> bool:
    if isinstance(value, bool):
        return False
    return isinstance(value, int) or (isinstance(value, float) and value.is_integer())


def _fmt(value: float, limit: Limit) -> str:
    text = f"{value:g}"
    return f"{text} {limit.unit}" if limit.unit else text


def validate_program(program: Program | None, range_table: RangeTable | None = None) -> ValidationResult:
    """Shortcut for one-off checks: ``validate_program(program).is_valid``."""
    return ValidationEngine(range_table).validate(program)
