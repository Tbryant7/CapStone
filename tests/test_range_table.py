"""Safe range config file card: RangeTable loads validation/ranges.json and
the app refuses to start if the file is missing or invalid."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from validation import (  # noqa: E402
    DEFAULT_RANGES_PATH,
    REQUIRED_PARAMETERS,
    RangeTable,
    RangeTableError,
    load_or_exit_message,
)

GOOD = {
    "source": "test",
    "confirmed": True,
    "parameters": {
        "pulse_width": {"label": "pulse width", "unit": "µs", "min": 10, "max": 200},
        "amplitude": {"label": "amplitude", "unit": "mA", "min": 0, "max": 30},
        "frequency": {"label": "frequency", "unit": "Hz", "min": 1, "max": 100},
        "time_step": {"label": "time step", "unit": "ms", "min": 10, "max": 1000},
    },
}


def _write(tmp_path, data, name="ranges.json"):
    path = tmp_path / name
    path.write_text(data if isinstance(data, str) else json.dumps(data), encoding="utf-8")
    return path


def _without(param):
    data = json.loads(json.dumps(GOOD))
    del data["parameters"][param]
    return data


def test_committed_ranges_file_loads_and_has_every_parameter():
    table = RangeTable.load(DEFAULT_RANGES_PATH)
    for name in REQUIRED_PARAMETERS:
        limit = table[name]
        assert limit.min <= limit.max
        assert limit.unit


def test_committed_ranges_file_names_its_source():
    table = RangeTable.load()
    assert table.source.strip()
    if not table.confirmed:
        assert "PLACEHOLDER" in table.source


def test_loads_values_label_and_unit(tmp_path):
    table = RangeTable.load(_write(tmp_path, GOOD))
    amp = table["amplitude"]
    assert (amp.min, amp.max, amp.unit, amp.label) == (0, 30, "mA", "amplitude")
    assert table.confirmed is True
    assert amp.contains(0) and amp.contains(30) and not amp.contains(30.1)


def test_missing_file_is_refused(tmp_path):
    with pytest.raises(RangeTableError, match="not found"):
        RangeTable.load(tmp_path / "nope.json")


@pytest.mark.parametrize(
    "bad, match",
    [
        ("{not json", "could not be read"),
        ("[]", "JSON object"),
        ({"confirmed": True}, "parameters"),
        (_without("amplitude"), "no limits for: amplitude"),
        ({**GOOD, "parameters": {**GOOD["parameters"], "amplitude": {"min": 5, "max": 1}}},
         "greater than max"),
        ({**GOOD, "parameters": {**GOOD["parameters"], "amplitude": {"min": "0", "max": 3}}},
         "must be a number"),
        ({**GOOD, "parameters": {**GOOD["parameters"], "frequency": {"min": 1}}},
         "max must be a number"),
        ({**GOOD, "parameters": {**GOOD["parameters"], "time_step": {"min": True, "max": 9}}},
         "must be a number"),
        ({**GOOD, "parameters": {**GOOD["parameters"], "pulse_width": 50}}, "must be an object"),
        ({**GOOD, "confirmed": "yes"}, "true or false"),
    ],
)
def test_invalid_files_are_refused(tmp_path, bad, match):
    with pytest.raises(RangeTableError, match=match):
        RangeTable.load(_write(tmp_path, bad))


def test_unconfirmed_limits_start_with_a_warning(tmp_path):
    table, message = load_or_exit_message(_write(tmp_path, {**GOOD, "confirmed": False}))
    assert table is not None
    assert "PLACEHOLDER" in message


def test_confirmed_limits_start_quietly(tmp_path):
    table, message = load_or_exit_message(_write(tmp_path, GOOD))
    assert table is not None and message == ""


@pytest.mark.parametrize("entry", ["run_app", "run_gui"])
def test_app_refuses_to_start_without_a_valid_ranges_file(tmp_path, capsys, entry):
    if entry == "run_gui":
        pytest.importorskip("PySide6.QtWidgets")
    module = __import__(entry)
    assert module.main(["--fake", "--ranges", str(tmp_path / "missing.json")]) == 1
    assert "Cannot start" in capsys.readouterr().out

    bad = _write(tmp_path, _without("time_step"), "bad.json")
    assert module.main(["--fake", "--ranges", str(bad)]) == 1
    assert "time_step" in capsys.readouterr().out
