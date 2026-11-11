"""The "one variable per channel and parameter" layout, as Prof. LaMack wrote it::

    t      = 0.000, 0.001, 0.002, ..., 10.000
    pw1    = ...        a1 = ...        freq1 = ...
    pw2    = ...        a2 = ...        freq2 = ...

Used by the .mat, .txt and .csv imports (``files/matlab_import.py``).

* ``t`` (or ``time`` / ``time_s``): seconds from the start, one fixed step apart.
* For each channel N: pulse width ``pwN``, amplitude ``aN`` (or ``ampN``) and
  frequency ``freqN`` (or ``fN``). Each is one value per time step, or a
  single value meaning "the same the whole time". Any of them, frequency
  included, may change from step to step.

Units. By default the values are in SI units, as in the example above:
time and pulse width in **seconds**, amplitude in **amps**, frequency in
**Hz**. ``units = 'us_mA'`` says pulse widths are in µs and amplitudes in mA
instead (the app's own units). A unit suffix on a name overrides both, e.g.
``pw1_us``, ``a1_ma``, ``pw1_s``, ``a1_a``, ``pw1_ms``, ``a1_ua``. The CSV-style
names ``ch1_pulse_width_us`` / ``ch1_amplitude_ma`` / ``ch1_frequency_hz`` work too.

A unit mix-up is a factor of 1000 or more, so values in seconds or amps that
are far too large to be real (pulse width over 10 ms, amplitude over 100 mA)
are refused with a message, instead of being converted.
"""

from __future__ import annotations

import re
from typing import Any

#: Name pattern: parameter, channel number, optional unit suffix.
_NAME = re.compile(
    r"^(?P<param>pw|pulse_?width|a|amp|amplitude|f|freq|frequency)_?(?P<ch>\d+)"
    r"(?:_(?P<unit>s|ms|us|a|ma|ua|hz))?$"
)
_CSV_NAME = re.compile(r"^ch(?P<ch>\d+)_(?P<param>pulse_width|amplitude|frequency)_(?P<unit>us|ma|hz)$")

_PARAM = {
    "pw": "pulse_width_us", "pulsewidth": "pulse_width_us", "pulse_width": "pulse_width_us",
    "a": "amplitude_ma", "amp": "amplitude_ma", "amplitude": "amplitude_ma",
    "f": "frequency_hz", "freq": "frequency_hz", "frequency": "frequency_hz",
}

#: Multiply by this to get the app's unit (µs, mA, Hz).
_TO_APP = {
    "pulse_width_us": {"s": 1e6, "ms": 1e3, "us": 1.0},
    "amplitude_ma": {"a": 1e3, "ma": 1.0, "ua": 1e-3},
    "frequency_hz": {"hz": 1.0},
}
_SHORT = {"pulse_width_us": "pw", "amplitude_ma": "a", "frequency_hz": "freq"}
_LABEL = {"pulse_width_us": "pulse width", "amplitude_ma": "amplitude", "frequency_hz": "frequency"}

#: Default units: SI (what Prof. LaMack's example uses), or the app's own.
_UNIT_SETS = {
    "si": {"pulse_width_us": "s", "amplitude_ma": "a", "frequency_hz": "hz"},
    "app": {"pulse_width_us": "us", "amplitude_ma": "ma", "frequency_hz": "hz"},
}
_UNITS_WORDS = {
    "si": "si", "s_a": "si", "seconds_amps": "si", "s,a": "si",
    "us_ma": "app", "us,ma": "app", "us/ma": "app", "app": "app", "device": "app", "wss": "app",
}

#: Values this large in seconds / amps are almost surely in µs / mA instead.
_TOO_BIG_SI = {"pulse_width_us": (0.01, "10 ms"), "amplitude_ma": (0.1, "100 mA")}

TIME_NAMES = ("t", "time", "time_s", "t_s")


def has_per_channel(data: dict) -> bool:
    """True if the variables look like pw1 / a1 / freq1 (or ch1_amplitude_ma ...)."""
    return any(_parse(name) for name in data)


def read_per_channel(data: dict, np, max_rows: int) -> tuple[list[float], list[dict], list[str], str]:
    """``(times, columns, problems, units_note)``; any problem means nothing is usable.

    ``columns`` has one dict per channel (``number``, and per-point
    ``pulse_width_us`` / ``amplitude_ma`` lists, and ``frequency_hz`` as one
    value or a per-point list) in the app's units, ready for
    ``matlab_import._build_program``.
    """
    problems: list[str] = []
    lower = {str(k).strip().lower(): (k, v) for k, v in data.items()}

    units_value = next((v for k, (_, v) in lower.items() if k == "units"), None)
    default_set = "si"
    if units_value is not None:
        word = _text(units_value, np).lower().replace(" ", "")
        default_set = _UNITS_WORDS.get(word)
        if default_set is None:
            problems.append(f"units = '{_text(units_value, np)}' isn't recognized: use 'SI' "
                            "(seconds, amps) or 'us_mA' (microseconds, milliamps).")
            default_set = "si"

    # time
    time_key = next((k for k in TIME_NAMES if k in lower), None)
    times = None
    if time_key is None:
        problems.append("Time is missing: add t (seconds from the start, e.g. 0, 0.001, 0.002, ...).")
    else:
        name, value = lower[time_key]
        times = _values(value, name, np, problems)
        if times is not None and len(times) > max_rows:
            problems.append(f"{name} has {len(times)} values, more than the {max_rows} the app accepts.")
            times = None

    # channel variables
    found: dict[int, dict[str, tuple[str, Any, str]]] = {}
    for key, (name, value) in lower.items():
        parsed = _parse(key)
        if not parsed:
            continue
        param, ch, unit = parsed
        unit = unit or _UNIT_SETS[default_set][param]
        if unit not in _TO_APP[param]:
            problems.append(f"{name}: '{unit}' is not a unit for {_LABEL[param]}.")
            continue
        slot = found.setdefault(ch, {})
        if param in slot:
            problems.append(f"Channel {ch} {_LABEL[param]} is given twice ({slot[param][0]} and {name}).")
            continue
        slot[param] = (name, value, unit)

    if not found:
        problems.append("No channel data found (e.g. pw1, a1, freq1).")
    columns: list[dict] = []
    n = len(times) if times is not None else None
    for ch in sorted(found):
        slot = found[ch]
        missing = [f"{_SHORT[p]}{ch}" for p in _TO_APP if p not in slot]
        if missing:
            problems.append(f"Channel {ch} is missing {', '.join(missing)} "
                            f"(each channel needs pw{ch}, a{ch} and freq{ch}).")
            continue
        column: dict[str, Any] = {"number": ch}
        for param, (name, value, unit) in slot.items():
            values = _values(value, name, np, problems)
            if values is None or n is None:
                continue
            if len(values) == 1:
                values = values * n
            elif len(values) != n:
                problems.append(f"{name} has {len(values)} values but t has {n} "
                                "(give one value per time step, or a single value).")
                continue
            if unit in ("s", "a"):
                limit, words = _TOO_BIG_SI.get(param, (None, ""))
                biggest = max(abs(v) for v in values)
                if limit is not None and biggest > limit:
                    problems.append(
                        f"{name} goes up to {biggest:g}, which read as {'seconds' if unit == 's' else 'amps'} "
                        f"is more than {words}. If these values are in µs / mA, add units = 'us_mA' "
                        f"(or name it {_SHORT[param]}{ch}_{'us' if param == 'pulse_width_us' else 'ma'})."
                    )
                    continue
            factor = _TO_APP[param][unit]
            column[param] = [round(v * factor, 9) for v in values] if factor != 1.0 else values
        if len(column) == 4:
            freqs = column["frequency_hz"]
            column["frequency_hz"] = freqs[0] if len(set(freqs)) == 1 else freqs
            columns.append(column)

    if problems or times is None:
        return [], [], problems, ""
    used = {unit for slot in found.values() for (_, _, unit) in slot.values()}
    note = _units_note(used)
    return times, columns, [], note


def _parse(key: str):
    key = str(key).strip().lower()
    m = _NAME.match(key)
    if m:
        param = _PARAM[m.group("param")]
        return param, int(m.group("ch")), m.group("unit")
    m = _CSV_NAME.match(key)
    if m:
        param = {"pulse_width": "pulse_width_us", "amplitude": "amplitude_ma",
                 "frequency": "frequency_hz"}[m.group("param")]
        return param, int(m.group("ch")), m.group("unit")
    return None


def _values(value, name, np, problems) -> list[float] | None:
    try:
        arr = np.asarray(value, dtype=float)
    except (TypeError, ValueError):
        problems.append(f"{name} must contain numbers.")
        return None
    if arr.ndim > 2 or (arr.ndim == 2 and min(arr.shape) > 1):
        problems.append(f"{name} must be a single row or column of values "
                        f"(got {arr.shape[0]} x {arr.shape[1]}).")
        return None
    flat = arr.reshape(-1)
    if flat.size == 0:
        problems.append(f"{name} is empty.")
        return None
    if not np.all(np.isfinite(flat)):
        problems.append(f"{name} has empty (NaN) or infinite values.")
        return None
    return [float(v) for v in flat]


def _units_note(units: set[str]) -> str:
    words = {"s": "seconds", "ms": "ms", "us": "µs", "a": "amps", "ma": "mA", "ua": "µA"}
    pw = sorted(words[u] for u in units if u in ("s", "ms", "us"))
    amp = sorted(words[u] for u in units if u in ("a", "ma", "ua"))
    return f"pulse width read in {'/'.join(pw)}, amplitude in {'/'.join(amp)}, frequency in Hz"


def _text(value, np) -> str:
    if isinstance(value, str):
        return value.strip()
    return " ".join(str(v).strip() for v in np.asarray(value).reshape(-1) if str(v).strip())
