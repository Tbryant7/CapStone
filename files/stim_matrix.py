"""The "stimulation matrix" .mat layout: one row per time step, one column per
channel and parameter. Shared by the MATLAB import and the New Program
screen's "Export .mat", so MATLAB scripts and the app use the same format.

A MATLAB script only has to choose:

1. the total time length  (``total_time_s``)
2. the number of active channels  (``num_channels``)
3. optionally the time step  (``time_step_ms``, or ``time_step_s``)

and save a matrix ``stim`` with

    rows    = total_time_s / time step + 1      (t = 0, step, 2*step, ..., total)
    columns = num_channels * number of parameters

Columns go channel by channel, each channel's parameters in the same order::

    [ch1_pulse_width_us, ch1_amplitude_ma, ch2_pulse_width_us, ch2_amplitude_ma, ...]

The parameter order is set by ``parameters`` (e.g. ``{'pulse_width_us',
'amplitude_ma', 'frequency_hz'}``). Without it the number of columns per
channel decides: 1 = amplitude, 2 = pulse width + amplitude,
3 = pulse width + amplitude + frequency. A parameter that isn't in the matrix
comes from its own variable instead (one value, or one per channel), e.g.
``frequency_hz = 20``. ``column_order = 'parameter'`` groups the columns by
parameter instead ([all channels' pulse widths, all amplitudes, ...]).

Optional: ``channels`` (channel numbers, default 1..num_channels), ``name``,
``description``. If ``time_step_ms`` is left out it is total_time_s / (rows - 1).
"""

from __future__ import annotations

import math
from typing import Any

from .program import Program

#: Parameter names, in the default column order, with accepted short names.
PARAMETERS = {
    "pulse_width_us": ("pulse_width_us", "pulse_width", "pw"),
    "amplitude_ma": ("amplitude_ma", "amplitude", "amp"),
    "frequency_hz": ("frequency_hz", "frequency", "freq"),
}

#: Default parameters for 1, 2 or 3 columns per channel.
DEFAULT_ORDER = {
    1: ("amplitude_ma",),
    2: ("pulse_width_us", "amplitude_ma"),
    3: ("pulse_width_us", "amplitude_ma", "frequency_hz"),
}

#: Accepted variable names (first is the documented one).
VARIABLES = {
    "stim": ("stim", "stimulation", "stim_matrix", "data"),
    "total_time_s": ("total_time_s", "total_time", "duration_s"),
    "num_channels": ("num_channels", "active_channels", "n_channels", "num_active_channels"),
    "time_step_ms": ("time_step_ms",),
    "time_step_s": ("time_step_s", "dt"),
    "parameters": ("parameters", "params"),
    "column_order": ("column_order",),
    "channels": ("channels", "channel"),
}

#: Rows above this are refused (a typo in the time step could mean millions).
MAX_ROWS = 2_000_000


def has_matrix(data: dict) -> bool:
    """True if a loaded .mat file uses this layout (it has a ``stim`` matrix)."""
    return _pick(data, "stim") is not None


def read_matrix(data: dict, np) -> tuple[list[float], list[dict], list[str]]:
    """Turn the variables of a .mat file into ``(times, columns, problems)``.

    ``columns`` has one dict per channel with ``number``, ``frequency_hz``
    and per-point ``pulse_width_us`` / ``amplitude_ma`` lists, ready for
    ``matlab_import._build_program``. Any problem means nothing is usable.
    """
    problems: list[str] = []
    stim = _array(_pick(data, "stim"), "stim", problems, np)
    if stim is None:
        return [], [], problems
    if stim.ndim == 1:
        stim = stim.reshape(-1, 1)
    if stim.ndim != 2:
        return [], [], ["stim must be a 2-D matrix (rows = time steps, columns = channels x parameters)."]
    if not np.all(np.isfinite(stim)):
        problems.append("stim has empty (NaN) or infinite values.")
    rows, width = stim.shape

    # 1) total time length
    total = _scalar(_pick(data, "total_time_s"), "total_time_s", problems, np, required=True)
    # 2) number of active channels
    numbers = _numbers(_pick(data, "channels"), np, problems)
    c = _scalar(_pick(data, "num_channels"), "num_channels", problems, np, required=numbers is None)
    if c is None and numbers is not None:
        c = len(numbers)
    if c is not None:
        if not float(c).is_integer() or c < 1:
            problems.append(f"num_channels must be a whole number, 1 or more (got {c:g}).")
            c = None
        else:
            c = int(c)
            if numbers is not None and len(numbers) != c:
                problems.append(f"channels lists {len(numbers)} channel numbers but num_channels is {c}.")
    # 3) time step (optional)
    step_ms = _scalar(_pick(data, "time_step_ms"), "time_step_ms", problems, np)
    if step_ms is None:
        step_s = _scalar(_pick(data, "time_step_s"), "time_step_s", problems, np)
        step_ms = step_s * 1000.0 if step_s is not None else None
    if problems or total is None or c is None:
        return [], [], problems

    if total < 0:
        return [], [], [f"total_time_s must be 0 or more (got {total:g})."]
    if step_ms is None:
        if rows < 2:
            return [], [], ["Give time_step_ms: with a single row it can't be worked out from total_time_s."]
        step_ms = total * 1000.0 / (rows - 1)
    if step_ms <= 0:
        return [], [], [f"The time step must be more than 0 ms (got {step_ms:g})."]
    exact = total * 1000.0 / step_ms
    expected = round(exact)
    if abs(exact - expected) > 1e-6 * max(1.0, exact):
        problems.append(
            f"total_time_s ({total:g} s) is not a whole number of {step_ms:g} ms time steps."
        )
    elif expected + 1 > MAX_ROWS:
        problems.append(f"{expected + 1} time steps is more than the {MAX_ROWS} the app accepts.")
    elif rows != expected + 1:
        problems.append(
            f"stim has {rows} rows but total_time_s / time step + 1 = "
            f"{total:g} s / {step_ms:g} ms + 1 = {expected + 1}."
        )

    order = _parameters(data, width, c, np, problems)
    by_parameter = str(_text(_pick(data, "column_order"))).lower().startswith("param")
    if problems:
        return [], [], problems

    p = len(order)
    # Parameters not in the matrix come from their own variables.
    constants = {
        name: _per_channel(data, name, c, np, problems)
        for name in PARAMETERS if name not in order
    }
    if problems:
        return [], [], problems
    columns = []
    for k in range(c):
        values = {}
        for j, name in enumerate(order):
            index = j * c + k if by_parameter else k * p + j
            values[name] = [float(v) for v in stim[:, index]]
        for name in ("pulse_width_us", "amplitude_ma"):
            if name not in values:
                values[name] = [constants[name][k]] * rows
        if "frequency_hz" in values:
            freqs = set(values["frequency_hz"])
            if len(freqs) > 1:
                problems.append(
                    f"Channel {k + 1} frequency changes over time; it must stay the same in every row."
                )
            frequency = values["frequency_hz"][0]
        else:
            frequency = constants["frequency_hz"][k]
        columns.append({
            "number": numbers[k] if numbers else k + 1,
            "frequency_hz": frequency,
            "amplitude_ma": values["amplitude_ma"],
            "pulse_width_us": values["pulse_width_us"],
        })
    if problems:
        return [], [], problems
    times = [round(i * step_ms / 1000.0, 9) for i in range(rows)]
    return times, columns, []


def matrix_variables(program: Program) -> dict[str, Any]:
    """The .mat variables for ``program`` in this layout (all three parameters).

    Constant channels become one row per time step with the same values, so
    every exported file has the shape a MATLAB script would write.
    """
    import numpy as np

    step_ms = float(program.time_step_ms)
    lengths = {len(ch.time_series) for ch in program.channels if ch.time_series}
    if len(lengths) > 1:
        raise ValueError("Every channel's time series must have the same number of points.")
    rows = lengths.pop() if lengths else 1
    columns = []
    for ch in program.channels:
        if ch.time_series:
            pw = [p.pulse_width_us for p in ch.time_series]
            amp = [p.amplitude_ma for p in ch.time_series]
        else:
            pw, amp = [ch.pulse_width_us] * rows, [ch.amplitude_ma] * rows
        columns += [pw, amp, [ch.frequency_hz] * rows]
    stim = np.array(columns, dtype=float).T.reshape(rows, 3 * len(program.channels))
    return {
        "stim": stim,
        "total_time_s": round((rows - 1) * step_ms / 1000.0, 9),
        "num_channels": float(len(program.channels)),
        "time_step_ms": step_ms,
        "channels": np.array([[float(ch.number) for ch in program.channels]]),
        "parameters": np.array(list(DEFAULT_ORDER[3]), dtype=object),
        "name": program.name,
        "description": program.description,
    }


def export_mat(program: Program, path) -> None:
    """Write ``program`` as a .mat file in this layout (MATLAB v5/-v7 format)."""
    from scipy.io import savemat

    savemat(str(path), matrix_variables(program), format="5")


# ---------------------------------------------------------------- helpers


def _pick(data: dict, field: str):
    lower = {k.lower(): v for k, v in data.items()}
    for name in VARIABLES.get(field) or PARAMETERS[field]:
        if name in lower:
            return lower[name]
    return None


def _array(value, field, problems, np):
    if value is None:
        problems.append(f"{field} is missing.")
        return None
    try:
        return np.asarray(value, dtype=float)
    except (TypeError, ValueError):
        problems.append(f"{field} must contain numbers.")
        return None


def _scalar(value, field, problems, np, required=False):
    if value is None:
        if required:
            problems.append(f"{field} is missing.")
        return None
    try:
        arr = np.asarray(value, dtype=float).reshape(-1)
    except (TypeError, ValueError):
        problems.append(f"{field} must be a number.")
        return None
    if arr.size != 1 or not math.isfinite(arr[0]):
        problems.append(f"{field} must be a single number.")
        return None
    return float(arr[0])


def _numbers(value, np, problems):
    if value is None:
        return None
    try:
        flat = np.asarray(value, dtype=float).reshape(-1)
    except (TypeError, ValueError):
        problems.append("channels must contain channel numbers.")
        return None
    return [int(v) if float(v).is_integer() else float(v) for v in flat]


def _parameters(data, width, c, np, problems) -> tuple[str, ...]:
    given = _pick(data, "parameters")
    if given is not None:
        order = []
        for raw in _names(given, np):
            name = next((p for p, aliases in PARAMETERS.items() if raw.lower() in aliases), None)
            if name is None:
                problems.append(f'parameters: "{raw}" is not a stimulation parameter '
                                "(use pulse_width_us, amplitude_ma or frequency_hz).")
            elif name in order:
                problems.append(f'parameters lists "{raw}" twice.')
            else:
                order.append(name)
        if problems:
            return ()
        if width != c * len(order):
            problems.append(
                f"stim has {width} columns but {c} channels x {len(order)} parameters = {c * len(order)}."
            )
        return tuple(order)
    if width % c:
        problems.append(f"stim has {width} columns, which isn't a multiple of {c} channels.")
        return ()
    order = DEFAULT_ORDER.get(width // c)
    if order is None:
        problems.append(
            f"stim has {width // c} columns per channel; without a parameters list it must be "
            "1 (amplitude), 2 (pulse width, amplitude) or 3 (pulse width, amplitude, frequency)."
        )
        return ()
    return order


def _per_channel(data, name, c, np, problems) -> list:
    value = _pick(data, name)
    if value is None:
        problems.append(f"{name} is missing: put it in stim or save it as its own variable "
                        "(one value, or one per channel).")
        return [None] * c
    try:
        flat = np.asarray(value, dtype=float).reshape(-1)
    except (TypeError, ValueError):
        problems.append(f"{name} must contain numbers.")
        return [None] * c
    if flat.size == 1:
        return [float(flat[0])] * c
    if flat.size != c:
        problems.append(f"{name} has {flat.size} values but there are {c} channels.")
        return [None] * c
    return [float(v) for v in flat]


def _names(value, np) -> list[str]:
    """Text list from a MATLAB cell array, char matrix or string."""
    if isinstance(value, str):
        return [part for part in value.replace(",", " ").split() if part]
    names = []
    for item in np.asarray(value, dtype=object).reshape(-1):
        if isinstance(item, np.ndarray):
            names += _names(item, np) if item.dtype == object else [str(x).strip() for x in item.reshape(-1)]
        else:
            names += _names(str(item), np)
    return [n for n in names if n]


def _text(value) -> str:
    if value is None:
        return ""
    import numpy as np

    return " ".join(str(v).strip() for v in np.asarray(value).reshape(-1) if str(v).strip())
