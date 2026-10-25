"""RangeTable: the safe min/max for every stimulation parameter.

All safety limits live in one file, ``validation/ranges.json``, so changing a
limit never means digging through code. The app refuses to start if that file
is missing or invalid: running without limits is never allowed.

File format::

    {
      "source": "Where the numbers came from (e.g. COSMIIC email, date)",
      "confirmed": true,
      "parameters": {
        "amplitude": {"label": "amplitude", "unit": "mA", "min": 0, "max": 3},
        ...
      }
    }

Every parameter in ``REQUIRED_PARAMETERS`` must be present.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

#: Default location of the limits file.
DEFAULT_RANGES_PATH = Path(__file__).resolve().parent / "ranges.json"

#: Parameters every limits file must define (keys in "parameters").
REQUIRED_PARAMETERS = ("pulse_width", "amplitude", "frequency", "time_step")


class RangeTableError(Exception):
    """The limits file is missing or invalid. The app must not start."""


@dataclass(frozen=True)
class Limit:
    """Allowed range for one parameter. Both ends are allowed (inclusive)."""

    name: str
    label: str
    unit: str
    min: float
    max: float

    def contains(self, value: float) -> bool:
        return self.min <= value <= self.max


@dataclass(frozen=True)
class RangeTable:
    limits: dict[str, Limit]
    source: str = ""
    confirmed: bool = False
    path: Path | None = None

    def get(self, name: str) -> Limit:
        try:
            return self.limits[name]
        except KeyError:
            raise KeyError(f"No safe range defined for '{name}'.") from None

    def __getitem__(self, name: str) -> Limit:
        return self.get(name)

    # ------------------------------------------------------------ loading

    @classmethod
    def load(cls, path: Path | str | None = None) -> "RangeTable":
        """Load and check the limits file. Raises :class:`RangeTableError`."""
        path = Path(path) if path is not None else DEFAULT_RANGES_PATH
        if not path.is_file():
            raise RangeTableError(f"Safe range file not found: {path}")
        try:
            with open(path, encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as ex:
            raise RangeTableError(f"Safe range file {path} could not be read: {ex}") from None
        try:
            table = cls.from_dict(data)
        except RangeTableError as ex:
            raise RangeTableError(f"Safe range file {path} is invalid: {ex}") from None
        return cls(table.limits, table.source, table.confirmed, path)

    @classmethod
    def from_dict(cls, data: Any) -> "RangeTable":
        """Build a table from already-parsed data (also used by tests)."""
        if not isinstance(data, dict):
            raise RangeTableError("top level must be a JSON object")
        params = data.get("parameters")
        if not isinstance(params, dict):
            raise RangeTableError('missing "parameters" object')

        missing = [name for name in REQUIRED_PARAMETERS if name not in params]
        if missing:
            raise RangeTableError(f"no limits for: {', '.join(missing)}")

        limits: dict[str, Limit] = {}
        for name, entry in params.items():
            if not isinstance(entry, dict):
                raise RangeTableError(f'"{name}" must be an object with min and max')
            low, high = entry.get("min"), entry.get("max")
            for which, value in (("min", low), ("max", high)):
                if not _is_number(value):
                    raise RangeTableError(f'"{name}" {which} must be a number, got {value!r}')
            if low > high:
                raise RangeTableError(f'"{name}" min ({low}) is greater than max ({high})')
            limits[name] = Limit(
                name=name,
                label=str(entry.get("label") or name.replace("_", " ")),
                unit=str(entry.get("unit") or ""),
                min=low,
                max=high,
            )

        confirmed = data.get("confirmed", False)
        if not isinstance(confirmed, bool):
            raise RangeTableError('"confirmed" must be true or false')
        return cls(limits, str(data.get("source", "")), confirmed)


def _is_number(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


def load_or_exit_message(path: Path | str | None = None) -> tuple[RangeTable | None, str]:
    """For app entry points: return ``(table, "")`` or ``(None, message)``.

    The caller prints the message and exits instead of starting the app.
    If the limits are not confirmed yet, the table is returned with a
    warning message the caller should show.
    """
    try:
        table = RangeTable.load(path)
    except RangeTableError as ex:
        return None, f"Cannot start: {ex}"
    if not table.confirmed:
        return table, (
            "WARNING: safety limits in validation/ranges.json are PLACEHOLDERS, "
            "not confirmed by COSMIIC."
        )
    return table, ""
