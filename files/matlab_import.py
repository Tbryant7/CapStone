"""Import time-series stimulation data from MATLAB (.mat) or CSV (REQ-15, UC4).

    program = import_time_series("ramp.mat")      # or "ramp.csv"

The result is an ordinary :class:`~files.program.Program` whose channels
carry time series. It is not validated here; ``ProgramFileManager.open``
runs the ValidationEngine on it like any other program (UC4 step 4).

Import is all or nothing (UC4-A1): if anything required is missing or the
shapes don't line up, :class:`~files.program_file_manager.ProgramFileError`
is raised with every problem listed, and no program is returned.

Expected layout (see docs/MATLAB_IMPORT.md and samples/matlab/):

.mat, saved from MATLAB with ``save(file, ..., '-v7')`` (the default), or
.txt, in any of three layouts:

* one variable per channel and parameter, as in Prof. LaMack's example:
  ``t``, ``pw1``, ``a1``, ``freq1``, ``pw2``, ... in seconds, amps and Hz by
  default (see ``files/per_channel.py``),

* one ``stim`` matrix, rows = time steps and columns = channels x
  parameters, with ``total_time_s``, ``num_channels`` and optionally
  ``time_step_ms`` (see ``files/stim_matrix.py``), or
* separate variables:

    time_s         N values, seconds from the start, one fixed step apart
    amplitude_ma    N x C (one column per channel), or 1 x C / scalar if constant
    pulse_width_us  N x C, or 1 x C / scalar if constant
    frequency_hz    N x C if it changes over time, or 1 x C / a scalar
    channels        optional 1 x C channel numbers (default 1..C)
    name            optional text
    description     optional text

.csv, header row then one row per time step:

    time_s, ch1_amplitude_ma, ch1_pulse_width_us, ch1_frequency_hz, ch2_amplitude_ma, ...

or with the per-channel names (``t, pw1, a1, freq1, pw2, ...``).

.txt, either ``name = v1, v2, v3, ...`` lines (one variable per line, as in
Prof. LaMack's email) or a table: a header row of names, then one row of
numbers per time step (separated by commas, tabs or spaces).

Short variable names are accepted too (``t``/``time``, ``amplitude``/``amp``,
``pulse_width``/``pw``, ``frequency``/``freq``).
"""

from __future__ import annotations

import csv
import math
import re
from pathlib import Path
from typing import Any

from .program import Channel, Program, TimeSeriesPoint
from .program_file_manager import ProgramFileError
from .per_channel import has_per_channel, read_per_channel
from .stim_matrix import MAX_ROWS, has_matrix, read_matrix

IMPORT_SUFFIXES = (".mat", ".csv", ".txt")

#: Accepted names for each field, first one is the documented name.
ALIASES = {
    "time_s": ("time_s", "time", "t"),
    "amplitude_ma": ("amplitude_ma", "amplitude", "amp"),
    "pulse_width_us": ("pulse_width_us", "pulse_width", "pw"),
    "frequency_hz": ("frequency_hz", "frequency", "freq"),
    "channels": ("channels", "channel"),
    "name": ("name",),
    "description": ("description",),
}

LABELS = {
    "time_s": "time (time_s)",
    "amplitude_ma": "amplitude (amplitude_ma)",
    "pulse_width_us": "pulse width (pulse_width_us)",
    "frequency_hz": "frequency (frequency_hz)",
}


def import_time_series(path: Path | str) -> Program:
    """Read a .mat, .csv or .txt time-series file into a Program. All or nothing."""
    path = Path(path)
    if not path.is_file():
        raise ProgramFileError(f"File not found: {path}")
    suffix = path.suffix.lower()
    if suffix == ".mat":
        return _from_mat(path)
    if suffix == ".csv":
        return _from_csv(path)
    if suffix == ".txt":
        return _from_txt(path)
    raise ProgramFileError(f"{path.name}: only .mat, .csv and .txt files can be imported.")


# ---------------------------------------------------------------- .mat


def _from_mat(path: Path) -> Program:
    try:
        import numpy as np
        from scipy.io import loadmat
    except ImportError:
        raise ProgramFileError(
            "MATLAB import needs scipy. Run: pip install -r requirements.txt"
        ) from None

    try:
        raw = loadmat(str(path), squeeze_me=False, chars_as_strings=True)
    except NotImplementedError:
        raise ProgramFileError(
            f"{path.name} was saved in MATLAB's v7.3 format, which can't be read yet. "
            "In MATLAB, save it again with:  save('file.mat', ..., '-v7')"
        ) from None
    except Exception as ex:  # scipy raises several types for damaged files
        raise ProgramFileError(f"{path.name} is not a readable MATLAB file ({ex}).") from None

    data = {k: v for k, v in raw.items() if not k.startswith("__")}
    return _from_variables(path, data, np)


def _from_variables(path: Path, data: dict, np) -> Program:
    """Any of the three layouts, from variables read out of a .mat or .txt file."""
    # One stim matrix: rows = time steps, columns = channels x parameters
    # (files/stim_matrix.py).
    if has_matrix(data):
        times, columns, problems = read_matrix(data, np)
        if problems:
            _fail(path, problems, sorted(data))
        return _build_program(
            path, times, columns,
            _text(_pick(data, "name")) or path.stem,
            _text(_pick(data, "description")) or f"Imported from {path.name}",
        )

    # One variable per channel and parameter: t, pw1, a1, freq1, pw2, ...
    if has_per_channel(data):
        times, columns, problems, note = read_per_channel(data, np, MAX_ROWS)
        if problems:
            _fail(path, problems, sorted(data))
        return _build_program(
            path, times, columns,
            _text(_pick(data, "name")) or path.stem,
            _text(_pick(data, "description")) or f"Imported from {path.name} ({note})",
        )

    problems: list[str] = []
    found = {field: _pick(data, field) for field in ALIASES}

    time = _vector(found["time_s"], "time_s", problems, np)
    columns = None
    if time is not None:
        n = len(time)
        varying = {}
        for field in ("amplitude_ma", "pulse_width_us"):
            varying[field] = _matrix(found[field], field, n, problems, np)
        counts = {m.shape[1] for m in varying.values() if m is not None and m.shape[0] == n and m.shape[1] > 1}
        widths = {m.shape[1] for m in varying.values() if m is not None}
        if len(counts) > 1:
            problems.append(
                "amplitude_ma and pulse_width_us have different numbers of channels "
                f"({' and '.join(str(c) for c in sorted(counts))} columns)."
            )
        c = max(widths) if widths else 0
        for field, m in varying.items():
            if m is not None and m.shape[1] not in (1, c):
                problems.append(
                    f"{LABELS[field]} has {m.shape[1]} columns but the data has {c} channels "
                    "(use one column per channel, or a single value for all)."
                )
        frequency = _frequencies(found["frequency_hz"], c, n, problems, np)
        numbers = _channel_numbers(found["channels"], c, problems, np)
        if c and not problems:
            columns = []
            for k in range(c):
                columns.append({
                    "number": numbers[k],
                    "frequency_hz": frequency[k],
                    "amplitude_ma": _column(varying["amplitude_ma"], k, n),
                    "pulse_width_us": _column(varying["pulse_width_us"], k, n),
                })

    if problems or columns is None:
        _fail(path, problems or ["No channel data found."], sorted(data))
    return _build_program(
        path,
        [float(t) for t in time],
        columns,
        _text(found["name"]) or path.stem,
        _text(found["description"]) or f"Imported from {path.name}",
    )


def _pick(data: dict, field: str):
    lower = {k.lower(): v for k, v in data.items()}
    for name in ALIASES[field]:
        if name in lower:
            return lower[name]
    return None


def _vector(value, field, problems, np):
    if value is None:
        problems.append(f"{LABELS[field]} is missing.")
        return None
    arr = _numeric(value, field, problems, np)
    if arr is None:
        return None
    if arr.ndim != 2 or min(arr.shape) != 1 or arr.size < 1:
        problems.append(f"{LABELS[field]} must be a single row or column of values (got {arr.shape[0]} x {arr.shape[1]}).")
        return None
    arr = arr.reshape(-1)
    if not np.all(np.isfinite(arr)):
        problems.append(f"{LABELS[field]} has empty (NaN) or infinite values.")
        return None
    return arr


def _matrix(value, field, n, problems, np):
    """N x C, or 1 x C / scalar meaning constant. Returns a 2-D array."""
    if value is None:
        problems.append(f"{LABELS[field]} is missing.")
        return None
    arr = _numeric(value, field, problems, np)
    if arr is None:
        return None
    if arr.shape[0] != n and arr.shape[1] == n and arr.shape[0] != 1:
        arr = arr.T  # channels given as rows instead of columns
    if arr.shape[0] not in (1, n):
        problems.append(
            f"{LABELS[field]} has {arr.shape[0]} rows but time_s has {n} values "
            "(use one row per time step, one column per channel)."
        )
        return None
    if not np.all(np.isfinite(arr)):
        problems.append(f"{LABELS[field]} has empty (NaN) or infinite values.")
        return None
    return arr


def _frequencies(value, c, n, problems, np):
    """frequency_hz: N x C (changes over time), or 1 x C / a scalar."""
    if value is not None:
        arr = np.asarray(value)
        if arr.ndim == 2 and n > 1 and n in arr.shape and arr.size >= n:
            m = _matrix(value, "frequency_hz", n, problems, np)
            if m is None:
                return [None] * c
            if m.shape[1] not in (1, c):
                problems.append(f"{LABELS['frequency_hz']} has {m.shape[1]} columns but the data has {c} channels.")
                return [None] * c
            return [_column(m, k, n) for k in range(c)]
    return _per_channel(value, "frequency_hz", c, problems, np)


def _per_channel(value, field, c, problems, np):
    if value is None:
        problems.append(f"{LABELS[field]} is missing (one value, or one per channel).")
        return [None] * c
    arr = _numeric(value, field, problems, np)
    if arr is None:
        return [None] * c
    flat = arr.reshape(-1)
    if flat.size == 1:
        return [float(flat[0])] * c
    if flat.size != c:
        problems.append(f"{LABELS[field]} has {flat.size} values but there are {c} channels.")
        return [None] * c
    return [float(v) for v in flat]


def _channel_numbers(value, c, problems, np):
    if value is None:
        return list(range(1, c + 1))
    arr = _numeric(value, "channels", problems, np)
    if arr is None:
        return list(range(1, c + 1))
    flat = arr.reshape(-1)
    if flat.size != c:
        problems.append(f"channels lists {flat.size} channel numbers but the data has {c} channels.")
        return list(range(1, c + 1))
    return [int(v) if float(v).is_integer() else float(v) for v in flat]


def _numeric(value, field, problems, np):
    try:
        arr = np.asarray(value, dtype=float)
    except (TypeError, ValueError):
        problems.append(f"{LABELS.get(field, field)} must contain numbers.")
        return None
    if arr.ndim == 0:
        arr = arr.reshape(1, 1)
    elif arr.ndim == 1:
        arr = arr.reshape(1, -1)
    elif arr.ndim > 2:
        problems.append(f"{LABELS.get(field, field)} must be a vector or a 2-D matrix.")
        return None
    return arr


def _column(matrix, k, n):
    if matrix.shape[1] == 1:
        k = 0  # one column / scalar: same values for every channel
    col = matrix[:, k] if k < matrix.shape[1] else matrix[:, -1]
    if matrix.shape[0] == 1:
        return [float(col[0])] * n
    return [float(v) for v in col]


def _text(value) -> str:
    if value is None:
        return ""
    try:
        import numpy as np

        flat = np.asarray(value).reshape(-1)
        return " ".join(str(v).strip() for v in flat if str(v).strip())
    except Exception:
        return str(value).strip()


# ---------------------------------------------------------------- .csv

_CSV_COLUMN = re.compile(r"^ch(\d+)_(amplitude_ma|pulse_width_us|frequency_hz)$")


def _from_csv(path: Path) -> Program:
    try:
        with open(path, newline="", encoding="utf-8-sig") as handle:
            rows = list(csv.reader(handle))
    except UnicodeDecodeError:
        raise ProgramFileError(f"{path.name} is not a text (CSV) file.") from None
    except (OSError, csv.Error) as ex:
        raise ProgramFileError(f"Could not read {path.name}: {ex}") from None

    rows = [r for r in rows if any(cell.strip() for cell in r)]
    if len(rows) < 2:
        _fail(path, ["The file needs a header row and at least one row of data."])

    header = [h.strip().lower() for h in rows[0]]
    if not any(_CSV_COLUMN.match(h) for h in header) and any(has_per_channel({h: 0}) for h in header):
        return _from_table(path, rows)
    problems: list[str] = []
    time_col = next((i for i, h in enumerate(header) if h in ALIASES["time_s"]), None)
    if time_col is None:
        problems.append("A time_s column is missing.")

    by_channel: dict[int, dict[str, int]] = {}
    for i, h in enumerate(header):
        m = _CSV_COLUMN.match(h)
        if m:
            by_channel.setdefault(int(m.group(1)), {})[m.group(2)] = i
        elif i != time_col and h:
            problems.append(f'Column "{rows[0][i].strip()}" is not recognized.')
    if not by_channel:
        problems.append("No channel columns found (e.g. ch1_amplitude_ma).")
    for ch, cols in sorted(by_channel.items()):
        for field in ("amplitude_ma", "pulse_width_us", "frequency_hz"):
            if field not in cols:
                problems.append(f"Channel {ch} is missing its ch{ch}_{field} column.")
    if problems:
        _fail(path, problems)

    values: list[list[float]] = []
    for line, row in enumerate(rows[1:], start=2):
        if len(row) < len(header):
            problems.append(f"Row {line} has {len(row)} values but the header has {len(header)} columns.")
            continue
        parsed = []
        for i, cell in enumerate(row[:len(header)]):
            try:
                number = float(cell)
                if not math.isfinite(number):
                    raise ValueError
            except ValueError:
                problems.append(f'Row {line}, column "{rows[0][i].strip()}": {cell.strip()!r} is not a number.')
                number = math.nan
            parsed.append(number)
        values.append(parsed)
        if len(problems) >= 10:
            problems.append("More rows have problems.")
            break
    if problems:
        _fail(path, problems)

    columns = []
    for ch, cols in sorted(by_channel.items()):
        columns.append({
            "number": ch,
            "frequency_hz": [v[cols["frequency_hz"]] for v in values],  # may change over time
            "amplitude_ma": [v[cols["amplitude_ma"]] for v in values],
            "pulse_width_us": [v[cols["pulse_width_us"]] for v in values],
        })
    if problems:
        _fail(path, problems)
    return _build_program(
        path, [v[time_col] for v in values], columns, path.stem, f"Imported from {path.name}"
    )


# ---------------------------------------------------------------- .txt

_SPLIT = re.compile(r"[\s,;\[\]]+")
_ASSIGN = re.compile(r"^\s*([A-Za-z][\w]*)\s*[=:]\s*(.*)$")


def _from_txt(path: Path) -> Program:
    """``name = 1, 2, 3`` lines, or a table with a header row."""
    try:
        import numpy as np
    except ImportError:
        raise ProgramFileError("Importing needs numpy. Run: pip install -r requirements.txt") from None
    try:
        text = path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError:
        raise ProgramFileError(f"{path.name} is not a text file.") from None
    except OSError as ex:
        raise ProgramFileError(f"Could not read {path.name}: {ex}") from None

    lines = [_strip_comment(line) for line in text.splitlines()]
    lines = [line for line in lines if line.strip()]
    if not lines:
        _fail(path, ["The file is empty."])
    if not _ASSIGN.match(lines[0]):
        rows = [[cell for cell in re.split(r"[,\t; ]+", line.strip()) if cell] for line in lines]
        return _from_table(path, rows)

    data: dict[str, Any] = {}
    texts: dict[str, list[str]] = {}
    raw: dict[str, list[str]] = {}
    problems: list[str] = []
    name = None
    for number, line in enumerate(lines, start=1):
        m = _ASSIGN.match(line)
        if m:
            name, rest = m.group(1), m.group(2)
            if name in data or name in texts:
                problems.append(f"{name} is given twice (line {number}).")
            data[name], texts[name], raw[name] = [], [], []
        elif name is None:
            problems.append(f"Line {number} doesn't start with a name (e.g. t = 0, 0.001, ...).")
            continue
        else:
            rest = line  # values carried on to the next line
        raw[name].append(rest.strip())
        for token in _SPLIT.split(rest.strip()):
            token = token.strip().strip("'\"")
            if not token:
                continue
            if token.strip(".…") == "":
                problems.append(f"{name} contains '{token}': every value must be written out.")
                continue
            try:
                data[name].append(float(token))
            except ValueError:
                texts[name].append(token)
    if problems:
        _fail(path, problems)
    variables: dict[str, Any] = {}
    for key, numbers in data.items():
        if texts[key] and not numbers:
            variables[key] = " ".join(raw[key]).strip().strip("'\"")  # name, description, units
        elif texts[key]:
            problems.append(f"{key}: {texts[key][0]!r} is not a number.")
        else:
            variables[key] = np.array([numbers])
    if problems:
        _fail(path, problems)
    return _from_variables(path, variables, np)


def _strip_comment(line: str) -> str:
    for mark in ("%", "#", "//"):
        if mark in line:
            line = line[:line.index(mark)]
    return line


def _from_table(path: Path, rows: list[list[str]]) -> Program:
    """Header row of variable names, then one row of numbers per time step."""
    import numpy as np

    header = [h.strip() for h in rows[0]]
    body = [r for r in rows[1:] if any(c.strip() for c in r)]
    problems: list[str] = []
    if not body:
        _fail(path, ["The file needs a header row and at least one row of numbers."])
    values = []
    for line, row in enumerate(body, start=2):
        if len(row) != len(header):
            problems.append(f"Row {line} has {len(row)} values but the header has {len(header)} names.")
        else:
            try:
                values.append([float(cell) for cell in row])
            except ValueError:
                bad = next(c for c in row if not _is_float(c))
                problems.append(f"Row {line}: {bad.strip()!r} is not a number.")
        if len(problems) >= 10:
            problems.append("More rows have problems.")
            break
    if problems:
        _fail(path, problems)
    table = np.array(values, dtype=float)
    data = {name: table[:, i].reshape(1, -1) for i, name in enumerate(header)}
    return _from_variables(path, data, np)


def _is_float(text: str) -> bool:
    try:
        float(text)
        return True
    except ValueError:
        return False


# ---------------------------------------------------------------- shared


def _build_program(path: Path, times: list[float], columns: list[dict], name: str, description: str) -> Program:
    step_ms = _time_step_ms(times)
    channels = []
    for col in columns:
        frequency = col["frequency_hz"]
        if isinstance(frequency, (list, tuple)) and len(set(frequency)) == 1:
            frequency = frequency[0]  # the same all the way down: keep it on the channel
        changing = isinstance(frequency, (list, tuple))
        points = [
            TimeSeriesPoint(time_s=t, pulse_width_us=pw, amplitude_ma=amp,
                            frequency_hz=frequency[i] if changing else None)
            for i, (t, pw, amp) in enumerate(zip(times, col["pulse_width_us"], col["amplitude_ma"]))
        ]
        channels.append(Channel(
            number=col["number"],
            pulse_width_us=points[0].pulse_width_us,
            amplitude_ma=points[0].amplitude_ma,
            frequency_hz=frequency[0] if changing else frequency,
            time_series=points,
        ))
    return Program(name=name, description=description, time_step_ms=step_ms, channels=channels)


def _time_step_ms(times: list[float]):
    """The fixed step between samples, in ms (the smallest positive gap).

    Uneven or backwards times are left for the ValidationEngine to report.
    A single sample has no step, so the time step is left missing.
    """
    gaps = [b - a for a, b in zip(times, times[1:]) if b - a > 0]
    if not gaps:
        return None
    return round(min(gaps) * 1000.0, 9)


def _fail(path: Path, problems: list[str], found: list[str] | None = None) -> None:
    message = f"{path.name} could not be imported, so nothing was loaded:\n" + "\n".join(
        f"- {p}" for p in problems
    )
    if found is not None:
        message += f"\nVariables in the file: {', '.join(found) or 'none'}."
    message += "\nSee docs/MATLAB_IMPORT.md for the expected layout."
    raise ProgramFileError(message)
