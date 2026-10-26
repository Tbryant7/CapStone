"""ProgramFileManager card: save/load round trip, damaged and incomplete files,
and the committed sample files.

Uses fixed test limits (like test_validation_engine.py) so the tests keep
working when the real COSMIIC numbers replace the placeholders.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from files import (  # noqa: E402
    Channel,
    Program,
    ProgramFileError,
    ProgramFileManager,
    ProgramValidationError,
)
from validation import RangeTable, ValidationEngine  # noqa: E402

SAMPLES = ROOT / "samples"

TEST_RANGES = RangeTable.from_dict({
    "source": "test limits",
    "confirmed": True,
    "parameters": {
        "pulse_width": {"label": "pulse width", "unit": "µs", "min": 20, "max": 200},
        "amplitude": {"label": "amplitude", "unit": "mA", "min": 0, "max": 3},
        "frequency": {"label": "frequency", "unit": "Hz", "min": 1, "max": 100},
        "time_step": {"label": "time step", "unit": "ms", "min": 10, "max": 1000},
    },
})


@pytest.fixture
def manager():
    return ProgramFileManager(ValidationEngine(TEST_RANGES))


def one_channel() -> Program:
    return Program("One channel", "Gentle test", 50, [Channel(1, 50, 1.0, 20)])


def four_channel() -> Program:
    return Program("Four channels", "", 25, [
        Channel(1, 50, 1.0, 20),
        Channel(2, 60, 1.5, 25),
        Channel(3, 40, 0.25, 20),
        Channel(4, 199, 2.75, 99),
    ])


def write(path: Path, data) -> Path:
    path.write_text(data if isinstance(data, str) else json.dumps(data), encoding="utf-8")
    return path


def good_data() -> dict:
    return one_channel().to_dict()


# ------------------------------------------------------------- round trip

@pytest.mark.parametrize("program", [
    one_channel(),
    four_channel(),
    Program("Ünïcode µs name", "Descriptions keep\nnew lines", 1000.0, [Channel(2, 20, 0, 1)]),
], ids=["1-channel", "4-channel", "unicode-and-floats"])
def test_saved_then_loaded_program_is_identical(manager, tmp_path, program):
    path = manager.save(program, tmp_path / "program.json")
    loaded = manager.load(path)
    assert loaded == program
    # Same types too (1.0 must not come back as 1, 50 not as 50.0).
    for before, after in zip(program.channels, loaded.channels):
        for field in ("number", "pulse_width_us", "amplitude_ma", "frequency_hz"):
            assert type(getattr(after, field)) is type(getattr(before, field))


@pytest.mark.parametrize("name", ["valid_1_channel.json", "valid_4_channel.json"])
def test_sample_load_save_load_is_identical(manager, tmp_path, name):
    first = manager.load(SAMPLES / name)
    second = manager.load(manager.save(first, tmp_path / name))
    assert second == first


def test_save_creates_missing_folders(manager, tmp_path):
    path = manager.save(one_channel(), tmp_path / "a" / "b" / "p.json")
    assert manager.load(path) == one_channel()


def test_saved_file_is_readable_json_in_the_documented_format(manager, tmp_path):
    path = manager.save(one_channel(), tmp_path / "p.json")
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data == {
        "format_version": 1,
        "name": "One channel",
        "description": "Gentle test",
        "time_step_ms": 50,
        "channels": [{"channel": 1, "pulse_width_us": 50, "amplitude_ma": 1.0, "frequency_hz": 20}],
    }


# ------------------------------------------------------------- saving unsafe programs

def test_save_refuses_unsafe_program_and_writes_nothing(manager, tmp_path):
    unsafe = Program("Too strong", "", 50, [Channel(1, 50, 40.0, 20)])
    path = tmp_path / "unsafe.json"
    with pytest.raises(ProgramValidationError) as info:
        manager.save(unsafe, path)
    assert "amplitude 40 mA is above the 3 mA limit" in str(info.value)
    assert not info.value.result.is_valid
    assert not path.exists()


def test_refused_save_leaves_existing_file_untouched(manager, tmp_path):
    path = manager.save(one_channel(), tmp_path / "p.json")
    before = path.read_bytes()
    with pytest.raises(ProgramValidationError):
        manager.save(Program("Bad", "", 50, []), path)
    assert path.read_bytes() == before


def test_failed_write_leaves_existing_file_and_no_temp_file(manager, tmp_path, monkeypatch):
    path = manager.save(one_channel(), tmp_path / "p.json")
    before = path.read_bytes()

    def broken_replace(src, dst):
        raise OSError("disk full")

    monkeypatch.setattr(os, "replace", broken_replace)
    with pytest.raises(ProgramFileError, match="disk full"):
        manager.save(four_channel(), path)
    assert path.read_bytes() == before
    assert [p.name for p in tmp_path.iterdir()] == ["p.json"]


# ------------------------------------------------------------- damaged / incomplete files

def _without(key):
    data = good_data()
    del data[key]
    return data


def _channel_with(**changes):
    data = good_data()
    data["channels"][0].update(changes)
    for key, value in list(changes.items()):
        if value is _DELETE:
            del data["channels"][0][key]
    return data


_DELETE = object()

DAMAGED = {
    "empty file": "",
    "cut off mid-save": json.dumps(good_data())[:-20],
    "not json": "this is not a program",
    "list instead of object": "[1, 2, 3]",
    "no format_version": _without("format_version"),
    "future format_version": {**good_data(), "format_version": 99},
    "no name": _without("name"),
    "blank name": {**good_data(), "name": "  "},
    "no time step": _without("time_step_ms"),
    "no channels": _without("channels"),
    "channels not a list": {**good_data(), "channels": {"channel": 1}},
    "empty channels": {**good_data(), "channels": []},
    "channel not an object": {**good_data(), "channels": [5]},
    "missing amplitude": _channel_with(amplitude_ma=_DELETE),
    "null pulse width": _channel_with(pulse_width_us=None),
    "text amplitude": _channel_with(amplitude_ma="high"),
    "true/false frequency": _channel_with(frequency_hz=True),
    "missing channel number": _channel_with(channel=_DELETE),
    "NaN amplitude": json.dumps(good_data()).replace('"amplitude_ma": 1.0', '"amplitude_ma": NaN'),
}


@pytest.mark.parametrize("contents", DAMAGED.values(), ids=DAMAGED.keys())
def test_damaged_or_incomplete_file_raises_and_loads_nothing(manager, tmp_path, contents):
    path = write(tmp_path / "broken.json", contents)
    loaded = "not set"
    with pytest.raises(ProgramFileError) as info:
        loaded = manager.load(path)
    assert loaded == "not set"           # nothing was returned, not even part of it
    assert "broken.json" in str(info.value)


def test_error_lists_every_missing_field(manager, tmp_path):
    data = good_data()
    del data["channels"][0]["amplitude_ma"]
    data["channels"][0]["pulse_width_us"] = None
    with pytest.raises(ProgramFileError) as info:
        manager.load(write(tmp_path / "p.json", data))
    message = str(info.value)
    assert "Channel entry 1 amplitude is missing." in message
    assert "Channel entry 1 pulse width is missing." in message


def test_binary_file_raises(manager, tmp_path):
    path = tmp_path / "picture.json"
    path.write_bytes(b"\x89PNG\r\n\x1a\n\xff\xfe\x00")
    with pytest.raises(ProgramFileError, match="not a text file"):
        manager.load(path)


def test_missing_file_raises(manager, tmp_path):
    with pytest.raises(ProgramFileError, match="File not found"):
        manager.load(tmp_path / "nope.json")


@pytest.mark.parametrize("name", ["missing_amplitude.json", "truncated.json"])
def test_committed_damaged_samples_refuse_to_load(manager, name):
    with pytest.raises(ProgramFileError):
        manager.load(SAMPLES / "damaged" / name)


# ------------------------------------------------------------- open (load + validate)

def test_open_valid_sample_passes(manager):
    opened = manager.open(SAMPLES / "valid_4_channel.json")
    assert len(opened.program.channels) == 4
    assert opened.validation.is_valid
    assert opened.path == SAMPLES / "valid_4_channel.json"


def test_unsafe_sample_opens_but_fails_validation(manager):
    """Unsafe values are not damage: the file opens so the screen can show why it fails."""
    opened = manager.open(SAMPLES / "unsafe_amplitude.json")
    assert opened.program.channels[1].amplitude_ma == 40.0
    assert not opened.validation.is_valid
    assert opened.validation.failed_parameters == [
        "Channel 2 amplitude 40 mA is above the 3 mA limit."
    ]


def test_default_manager_uses_committed_ranges():
    opened = ProgramFileManager().open(SAMPLES / "valid_1_channel.json")
    assert opened.validation.is_valid
