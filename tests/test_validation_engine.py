"""ValidationEngine card: values at, just under and just over every limit,
an empty program, missing values, and the sample files.

Most tests use their own fixed limits (TEST_RANGES) so they keep working when
the real COSMIIC numbers replace the placeholders in validation/ranges.json.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from files.program import Channel, Program  # noqa: E402
from validation import RangeTable, ValidationEngine, ValidationResult  # noqa: E402

SAMPLES = ROOT / "samples"

TEST_RANGES = RangeTable.from_dict({
    "source": "test limits",
    "confirmed": True,
    "parameters": {
        "pulse_width": {"label": "pulse width", "unit": "µs", "min": 20, "max": 200},
        "amplitude": {"label": "amplitude", "unit": "mA", "min": 0.5, "max": 30},
        "frequency": {"label": "frequency", "unit": "Hz", "min": 1, "max": 100},
        "time_step": {"label": "time step", "unit": "ms", "min": 10, "max": 1000},
    },
})

#: A small step for "just under" / "just over" each limit.
STEP = {"pulse_width": 1, "amplitude": 0.1, "frequency": 1, "time_step": 1}
FIELD = {"pulse_width": "pulse_width_us", "amplitude": "amplitude_ma", "frequency": "frequency_hz"}


def good_channel(number=1, **overrides) -> Channel:
    values = dict(number=number, pulse_width_us=50, amplitude_ma=1.0, frequency_hz=20)
    values.update(overrides)
    return Channel(**values)


def good_program(*channels: Channel, time_step_ms=50) -> Program:
    return Program("p", "", time_step_ms, list(channels) or [good_channel()])


@pytest.fixture
def engine():
    return ValidationEngine(TEST_RANGES)


def _value_cases():
    """(parameter, value, should_pass) at, just inside and just outside each end."""
    for param in ("pulse_width", "amplitude", "frequency", "time_step"):
        limit, step = TEST_RANGES[param], STEP[param]
        yield param, limit.min, True            # at min
        yield param, limit.min + step, True     # just above min
        yield param, limit.min - step, False    # just under min
        yield param, limit.max, True            # at max
        yield param, limit.max - step, True     # just under max
        yield param, limit.max + step, False    # just over max


@pytest.mark.parametrize("param, value, should_pass", list(_value_cases()))
def test_each_limit_at_just_under_and_just_over(engine, param, value, should_pass):
    value = round(value, 6)
    if param == "time_step":
        program = good_program(time_step_ms=value)
    else:
        program = good_program(good_channel(**{FIELD[param]: value}))

    result = engine.validate(program)
    assert result.is_valid is should_pass, result.failed_parameters
    if not should_pass:
        assert len(result.failed_parameters) == 1
        label = TEST_RANGES[param].label
        assert label in result.failed_parameters[0].lower()


def test_message_wording_matches_the_card(engine):
    program = good_program(good_channel(1), good_channel(2, amplitude_ma=40))
    result = engine.validate(program)
    assert result.failed_parameters == ["Channel 2 amplitude 40 mA is above the 30 mA limit."]
    assert result.isValid is False  # SDS names work too
    assert result.failedParameters == result.failed_parameters


def test_below_minimum_message(engine):
    result = engine.validate(good_program(good_channel(3, pulse_width_us=10)))
    assert result.failed_parameters == ["Channel 3 pulse width 10 µs is below the 20 µs minimum."]


def test_valid_program_passes_with_no_messages(engine):
    result = engine.validate(good_program(good_channel(1), good_channel(2), good_channel(3), good_channel(4)))
    assert result == ValidationResult(True, [])
    assert result.summary() == "Passed"


def test_every_problem_is_reported_not_just_the_first(engine):
    program = good_program(
        good_channel(1, amplitude_ma=99, frequency_hz=0),
        good_channel(2, pulse_width_us=500),
        time_step_ms=5,
    )
    result = engine.validate(program)
    assert len(result.failed_parameters) == 4
    assert result.summary() == "Failed: 4 problems"


# ------------------------------------------------------- empty / missing


def test_empty_program_fails(engine):
    result = engine.validate(Program(name="empty", time_step_ms=50, channels=[]))
    assert not result.is_valid
    assert result.failed_parameters == ["Program has no channels. Add at least one channel."]


def test_blank_program_reports_everything_missing(engine):
    result = engine.validate(Program())
    assert result.failed_parameters == [
        "Time step is missing.",
        "Program has no channels. Add at least one channel.",
    ]


def test_no_program_at_all(engine):
    assert engine.validate(None).failed_parameters == ["No program to check."]


def test_wrong_type_is_rejected(engine):
    assert not engine.validate({"channels": []}).is_valid


@pytest.mark.parametrize("field, label", [
    ("pulse_width_us", "pulse width"),
    ("amplitude_ma", "amplitude"),
    ("frequency_hz", "frequency"),
])
def test_missing_channel_value(engine, field, label):
    result = engine.validate(good_program(good_channel(2, **{field: None})))
    assert result.failed_parameters == [f"Channel 2 {label} is missing."]


def test_missing_time_step(engine):
    result = engine.validate(good_program(time_step_ms=None))
    assert result.failed_parameters == ["Time step is missing."]


def test_channel_with_nothing_filled_in(engine):
    result = engine.validate(good_program(Channel()))
    assert result.failed_parameters == [
        "Channel entry 1 has no channel number.",
        "Channel entry 1 pulse width is missing.",
        "Channel entry 1 amplitude is missing.",
        "Channel entry 1 frequency is missing.",
    ]


@pytest.mark.parametrize("bad", ["abc", "3", True, float("nan"), float("inf"), [1]])
def test_values_that_are_not_numbers(engine, bad):
    result = engine.validate(good_program(good_channel(1, amplitude_ma=bad)))
    assert not result.is_valid
    assert "not a number" in result.failed_parameters[0]


@pytest.mark.parametrize("bad", [0, -1, 1.5, "2", True])
def test_invalid_channel_numbers(engine, bad):
    result = engine.validate(good_program(good_channel(bad)))
    assert result.failed_parameters == [
        f"Channel entry 1 has an invalid channel number {bad!r} "
        "(must be a whole number, 1 or more)."
    ]


def test_whole_number_float_channel_is_accepted(engine):
    assert engine.validate(good_program(good_channel(2.0))).is_valid


def test_duplicate_channel_numbers(engine):
    result = engine.validate(good_program(good_channel(2), good_channel(2)))
    assert result.failed_parameters == ["Channel 2 appears more than once."]


def test_no_hard_coded_channel_maximum(engine):
    """Channel count comes from the device (REQ-23), not from validation."""
    assert engine.validate(good_program(good_channel(12))).is_valid


# ------------------------------------------------------------- samples


def _load_sample(name: str) -> Program:
    with open(SAMPLES / name, encoding="utf-8") as handle:
        return Program.from_dict(json.load(handle))


@pytest.mark.parametrize("name", ["valid_1_channel.json", "valid_4_channel.json"])
def test_valid_samples_pass_with_committed_ranges(name):
    result = ValidationEngine().validate(_load_sample(name))
    assert result.is_valid, result.failed_parameters


def test_unsafe_sample_fails_with_clear_message():
    result = ValidationEngine().validate(_load_sample("unsafe_amplitude.json"))
    assert not result.is_valid
    assert len(result.failed_parameters) == 1
    message = result.failed_parameters[0]
    assert message.startswith("Channel 2 amplitude 40 mA is above the")
    assert message.endswith("mA limit.")


def test_sample_channel_counts():
    assert len(_load_sample("valid_1_channel.json").channels) == 1
    assert len(_load_sample("valid_4_channel.json").channels) == 4


# ------------------------------------------ terminal command (python -m validation)


def test_command_line_reports_pass_and_fail(capsys):
    from validation.__main__ import main

    code = main([str(SAMPLES / "valid_4_channel.json"), str(SAMPLES / "unsafe_amplitude.json")])
    out = capsys.readouterr().out
    assert code == 1
    assert "valid_4_channel.json (Four channel test): PASSED" in out
    assert "unsafe_amplitude.json (Unsafe amplitude (demo)): FAILED" in out
    assert "Channel 2 amplitude 40 mA is above the" in out


def test_command_line_all_valid_exits_zero(capsys):
    from validation.__main__ import main

    assert main([str(SAMPLES / "valid_1_channel.json")]) == 0


def test_command_line_unreadable_file(tmp_path, capsys):
    from validation.__main__ import main

    broken = tmp_path / "broken.json"
    broken.write_text("{ not json", encoding="utf-8")
    assert main([str(broken), str(tmp_path / "missing.json")]) == 1
    out = capsys.readouterr().out
    assert out.count("COULD NOT READ") == 2


def test_command_line_refuses_missing_ranges(tmp_path, capsys):
    from validation.__main__ import main

    assert main([str(SAMPLES / "valid_1_channel.json"), "--ranges", str(tmp_path / "x.json")]) == 1
    assert "Cannot start" in capsys.readouterr().out
