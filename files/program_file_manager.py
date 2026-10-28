"""ProgramFileManager: saves a Program to a JSON file and loads it back.

    manager = ProgramFileManager()
    manager.save(program, "my_program.json")     # refuses an unsafe program
    program = manager.load("my_program.json")    # raises ProgramFileError if damaged
    opened = manager.open("my_program.json")     # load + ValidationEngine result

Loading is all or nothing. The whole file is checked before a Program is
built, so a damaged or incomplete file raises :class:`ProgramFileError` with
a plain-language message and nothing is half-loaded. "Incomplete" means a
required field is missing or empty (``null``); a file that is complete but
has unsafe values still loads, so the screen can show what is wrong with it.

Every load and save goes through the ValidationEngine (REQ-16, REQ-17):
``save`` refuses a program that fails validation, and ``open`` returns the
validation result next to the program.

The file format is the one in ``files/program.py`` (see ``samples/``).
"""

from __future__ import annotations

import json
import math
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .program import FORMAT_VERSION, Program

#: Channel fields every file must have: (JSON key, label in messages).
CHANNEL_FIELDS = (
    ("channel", "channel number"),
    ("pulse_width_us", "pulse width"),
    ("amplitude_ma", "amplitude"),
    ("frequency_hz", "frequency"),
)


class ProgramFileError(Exception):
    """The file could not be saved or loaded. The message says why, in words."""


class ProgramValidationError(ProgramFileError):
    """``save`` refused a program that failed validation."""

    def __init__(self, message: str, result: Any) -> None:
        super().__init__(message)
        self.result = result


@dataclass(frozen=True)
class OpenedProgram:
    """A program loaded from disk together with its validation result."""

    program: Program
    validation: Any  # validation.ValidationResult
    path: Path


class ProgramFileManager:
    def __init__(self, engine: Any = None) -> None:
        # Imported here because validation imports files.program.
        if engine is None:
            from validation import ValidationEngine
            engine = ValidationEngine()
        self.engine = engine

    # ------------------------------------------------------------ save

    def save(self, program: Program, path: Path | str) -> Path:
        """Write ``program`` to ``path`` as JSON and return the path.

        Refuses (raises :class:`ProgramValidationError`) if the program fails
        validation. The old file is only replaced once the new one is fully
        written, so a failed save never leaves a damaged file behind.
        """
        path = Path(path)
        result = self.engine.validate(program)
        if not result.is_valid:
            raise ProgramValidationError(
                "Not saved: the program failed validation.\n"
                + "\n".join(f"- {p}" for p in result.failed_parameters),
                result,
            )

        try:
            text = json.dumps(program.to_dict(), indent=2, ensure_ascii=False, allow_nan=False)
            path.parent.mkdir(parents=True, exist_ok=True)
            handle, temp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
            try:
                with os.fdopen(handle, "w", encoding="utf-8") as temp:
                    temp.write(text + "\n")
                os.replace(temp_name, path)
            except BaseException:
                Path(temp_name).unlink(missing_ok=True)
                raise
        except (OSError, TypeError, ValueError) as ex:
            raise ProgramFileError(f"Could not save {path}: {ex}") from None
        return path

    # ------------------------------------------------------------ load

    def load(self, path: Path | str) -> Program:
        """Read ``path`` and return the Program.

        Raises :class:`ProgramFileError` if the file is missing, unreadable,
        not valid JSON, or missing any required field. Does not check safe
        ranges; use :meth:`open` for that.
        """
        path = Path(path)
        try:
            with open(path, encoding="utf-8") as handle:
                data = json.load(handle, parse_constant=_reject_constant)
        except FileNotFoundError:
            raise ProgramFileError(f"File not found: {path}") from None
        except UnicodeDecodeError:
            raise ProgramFileError(f"{path.name} is not a text file.") from None
        except json.JSONDecodeError as ex:
            raise ProgramFileError(
                f"{path.name} is damaged: it is not valid JSON "
                f"(line {ex.lineno}, column {ex.colno}: {ex.msg})."
            ) from None
        except (OSError, ValueError) as ex:
            raise ProgramFileError(f"Could not read {path.name}: {ex}") from None

        problems = check_program_data(data)
        if problems:
            raise ProgramFileError(
                f"{path.name} is damaged or incomplete, so it was not opened:\n"
                + "\n".join(f"- {p}" for p in problems)
            )
        return Program.from_dict(data)

    def open(self, path: Path | str) -> OpenedProgram:
        """Load ``path`` and validate it. Raises :class:`ProgramFileError`.

        ``.mat`` and ``.csv`` files are imported as time-series data
        (``files/matlab_import.py``, REQ-15) and validated the same way.
        """
        path = Path(path)
        if path.suffix.lower() in (".mat", ".csv"):
            from .matlab_import import import_time_series

            program = import_time_series(path)
        else:
            program = self.load(path)
        return OpenedProgram(program, self.engine.validate(program), path)


def check_program_data(data: Any) -> list[str]:
    """Every reason ``data`` (parsed JSON) is not a complete program file.

    Empty list means it is safe to build a Program from it. Ranges are not
    checked here; that is the ValidationEngine's job.
    """
    if not isinstance(data, dict):
        return ["The file must contain one program (a JSON object)."]

    problems: list[str] = []
    version = data.get("format_version")
    if version is None:
        problems.append('"format_version" is missing.')
    elif version != FORMAT_VERSION:
        problems.append(
            f"format_version {version!r} is not supported (this app reads version {FORMAT_VERSION})."
        )

    if not isinstance(data.get("name"), str) or not data["name"].strip():
        problems.append("Program name is missing.")
    if "description" in data and data["description"] is not None and not isinstance(data["description"], str):
        problems.append("Description must be text.")

    _check_number(data, "time_step_ms", "Time step", problems)

    channels = data.get("channels")
    if channels is None:
        problems.append('"channels" is missing.')
    elif not isinstance(channels, list):
        problems.append('"channels" must be a list.')
    elif not channels:
        problems.append("Program has no channels.")
    else:
        for index, entry in enumerate(channels, start=1):
            if not isinstance(entry, dict):
                problems.append(f"Channel entry {index} is not a channel object.")
                continue
            for key, label in CHANNEL_FIELDS:
                _check_number(entry, key, f"Channel entry {index} {label}", problems)
            _check_time_series(entry, index, problems)
    return problems


#: Fields every time-series point must have: (JSON key, label in messages).
POINT_FIELDS = (
    ("time_s", "time"),
    ("pulse_width_us", "pulse width"),
    ("amplitude_ma", "amplitude"),
)


def _check_time_series(entry: dict, index: int, problems: list[str]) -> None:
    """``time_series`` is optional; when present every point must be complete."""
    points = entry.get("time_series")
    if points is None:
        return
    if not isinstance(points, list):
        problems.append(f'Channel entry {index} "time_series" must be a list.')
        return
    before = len(problems)
    for number, point in enumerate(points, start=1):
        if not isinstance(point, dict):
            problems.append(f"Channel entry {index} time-series point {number} is not a point object.")
        else:
            for key, label in POINT_FIELDS:
                _check_number(point, key, f"Channel entry {index} time-series point {number} {label}", problems)
        if len(problems) - before >= 5:  # don't bury the user in thousands of lines
            problems.append(f"Channel entry {index}: more time-series points have problems.")
            return


def _check_number(data: dict, key: str, what: str, problems: list[str]) -> None:
    value = data.get(key)
    if value is None:
        problems.append(f"{what} is missing.")
    elif isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        problems.append(f"{what} {value!r} is not a number.")


def _reject_constant(name: str) -> None:
    raise ValueError(f"{name} is not allowed in a program file")
