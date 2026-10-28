"""MATLAB / CSV time-series import (REQ-15, UC4): files become Programs with
per-channel time series, import is all or nothing (UC4-A1), and the
ValidationEngine checks every point (REQ-16, REQ-7 / UC2-A2)."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

np = pytest.importorskip("numpy")
scipy_io = pytest.importorskip("scipy.io")
savemat = scipy_io.savemat

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from files import (  # noqa: E402
    Channel,
    Program,
    ProgramFileError,
    ProgramFileManager,
    TimeSeriesPoint,
    import_time_series,
)
from validation import RangeTable, ValidationEngine  # noqa: E402

SAMPLES = ROOT / "samples" / "matlab"

TEST_RANGES = RangeTable.from_dict({
    "source": "test limits", "confirmed": True,
    "parameters": {
        "pulse_width": {"label": "pulse width", "unit": "µs", "min": 20, "max": 200},
        "amplitude": {"label": "amplitude", "unit": "mA", "min": 0, "max": 30},
        "frequency": {"label": "frequency", "unit": "Hz", "min": 1, "max": 100},
        "time_step": {"label": "time step", "unit": "ms", "min": 1, "max": 1000},
    },
})


@pytest.fixture
def engine():
    return ValidationEngine(TEST_RANGES)


def write_mat(path, **variables):
    savemat(path, variables, format="5")
    return path


def basic_vars(n=11, step=0.01, channels=2):
    t = np.round(np.arange(n) * step, 6).reshape(-1, 1)
    amp = np.column_stack([np.linspace(0, 2, n) * (k + 1) for k in range(channels)])
    return dict(time_s=t, amplitude_ma=amp, pulse_width_us=np.array([[50.0]]),
                frequency_hz=np.array([[20.0]]))


# ------------------------------------------------------------- .mat


def test_sample_mat_imports_as_two_time_series_channels(engine):
    program = import_time_series(SAMPLES / "ramp_2ch.mat")
    assert program.name == "Two channel ramp (demo)"
    assert program.time_step_ms == pytest.approx(20)
    assert [c.number for c in program.channels] == [1, 2]
    assert [c.frequency_hz for c in program.channels] == [20, 25]
    ch1 = program.channels[0]
    assert len(ch1.time_series) == 201
    assert ch1.time_series[0] == TimeSeriesPoint(0.0, 50.0, 0.0)
    assert max(p.amplitude_ma for p in ch1.time_series) == pytest.approx(2.5)
    assert {p.pulse_width_us for p in ch1.time_series} == {50.0}
    assert engine.validate(program).is_valid


def test_csv_sample_matches_the_mat_sample():
    from_mat = import_time_series(SAMPLES / "ramp_2ch.mat").to_dict()
    from_csv = import_time_series(SAMPLES / "ramp_2ch.csv").to_dict()
    for d in (from_mat, from_csv):
        d.pop("name"), d.pop("description")
    assert from_csv == from_mat


def test_short_names_channel_rows_and_custom_channel_numbers(tmp_path, engine):
    v = basic_vars(channels=3)
    path = write_mat(
        tmp_path / "short.mat",
        t=v["time_s"].T,                      # a row instead of a column
        amp=v["amplitude_ma"].T,              # channels as rows
        pw=np.array([[40.0, 50.0, 60.0]]),    # one per channel
        freq=np.array([[20.0]]),
        channels=np.array([[2, 3, 4]]),
    )
    program = import_time_series(path)
    assert [c.number for c in program.channels] == [2, 3, 4]
    assert [c.pulse_width_us for c in program.channels] == [40, 50, 60]
    assert len(program.channels[2].time_series) == 11
    assert program.name == "short"
    assert engine.validate(program).is_valid


def test_pulse_width_can_vary_over_time_too(tmp_path):
    v = basic_vars(channels=1)
    v["pulse_width_us"] = np.linspace(20, 120, 11).reshape(-1, 1)
    program = import_time_series(write_mat(tmp_path / "pw.mat", **v))
    assert program.channels[0].time_series[-1].pulse_width_us == pytest.approx(120)


@pytest.mark.parametrize("drop, message", [
    ("frequency_hz", "frequency (frequency_hz) is missing"),
    ("time_s", "time (time_s) is missing"),
    ("amplitude_ma", "amplitude (amplitude_ma) is missing"),
    ("pulse_width_us", "pulse width (pulse_width_us) is missing"),
])
def test_missing_variable_is_refused_and_listed(tmp_path, drop, message):
    v = basic_vars()
    del v[drop]
    with pytest.raises(ProgramFileError) as info:
        import_time_series(write_mat(tmp_path / "x.mat", **v))
    text = str(info.value)
    assert "could not be imported, so nothing was loaded" in text
    assert message in text
    assert "Variables in the file:" in text


def test_sample_with_missing_frequency_is_refused():
    with pytest.raises(ProgramFileError, match="frequency"):
        import_time_series(SAMPLES / "missing_frequency.mat")


@pytest.mark.parametrize("change, message", [
    (lambda v: v.update(amplitude_ma=np.ones((7, 2))), "has 7 rows but time_s has 11 values"),
    (lambda v: v.update(frequency_hz=np.array([[20.0, 25.0, 30.0]])), "has 3 values but there are 2 channels"),
    (lambda v: v.update(pulse_width_us=np.ones((11, 3))), "different numbers of channels"),
    (lambda v: v.update(amplitude_ma=np.full((11, 2), np.nan)), "NaN"),
    (lambda v: v.update(time_s=np.ones((3, 3))), "single row or column"),
    (lambda v: v.update(channels=np.array([[1, 2, 3]])), "lists 3 channel numbers"),
])
def test_shape_problems_are_refused(tmp_path, change, message):
    v = basic_vars()
    change(v)
    with pytest.raises(ProgramFileError, match=message):
        import_time_series(write_mat(tmp_path / "bad.mat", **v))


def test_v73_file_gets_a_clear_message(tmp_path):
    header = b"MATLAB 7.3 MAT-file, Platform: GLNXA64, Created on: Mon Oct 26 2026 HDF5 schema 1.00 ."
    header = header.ljust(116, b" ") + b"\x00" * 8 + b"\x00\x02" + b"IM"
    path = tmp_path / "big.mat"
    path.write_bytes(header + b"\x00" * 512)
    with pytest.raises(ProgramFileError, match="'-v7'"):
        import_time_series(path)


def test_damaged_mat_file_is_refused(tmp_path):
    path = tmp_path / "junk.mat"
    path.write_bytes(b"this is not a mat file at all" * 10)
    with pytest.raises(ProgramFileError, match="not a readable MATLAB file"):
        import_time_series(path)


def test_missing_file_and_wrong_type(tmp_path):
    with pytest.raises(ProgramFileError, match="not found"):
        import_time_series(tmp_path / "nope.mat")
    other = tmp_path / "x.txt"
    other.write_text("hi")
    with pytest.raises(ProgramFileError, match="only .mat and .csv"):
        import_time_series(other)


# ------------------------------------------------------------- .csv


def _csv(tmp_path, text):
    path = tmp_path / "data.csv"
    path.write_text(text, encoding="utf-8")
    return path


def test_csv_basic(tmp_path, engine):
    path = _csv(tmp_path, "time_s,ch1_amplitude_ma,ch1_pulse_width_us,ch1_frequency_hz\n"
                          "0,0,50,20\n0.01,1,50,20\n0.02,2,50,20\n")
    program = import_time_series(path)
    assert program.time_step_ms == pytest.approx(10)
    assert [p.amplitude_ma for p in program.channels[0].time_series] == [0, 1, 2]
    assert engine.validate(program).is_valid


@pytest.mark.parametrize("text, message", [
    ("ch1_amplitude_ma,ch1_pulse_width_us,ch1_frequency_hz\n1,50,20\n", "time_s column is missing"),
    ("time_s,ch1_amplitude_ma,ch1_frequency_hz\n0,1,20\n", "missing its ch1_pulse_width_us column"),
    ("time_s,ch1_amplitude_ma,ch1_pulse_width_us,ch1_frequency_hz,notes\n0,1,50,20,x\n", '"notes" is not recognized'),
    ("time_s,ch1_amplitude_ma,ch1_pulse_width_us,ch1_frequency_hz\n0,abc,50,20\n", "'abc' is not a number"),
    ("time_s,ch1_amplitude_ma,ch1_pulse_width_us,ch1_frequency_hz\n0,1,50\n", "Row 2 has 3 values"),
    ("time_s,ch1_amplitude_ma,ch1_pulse_width_us,ch1_frequency_hz\n0,1,50,20\n0.01,1,50,30\n", "same on every row"),
    ("time_s\n", "header row and at least one row"),
])
def test_csv_problems_are_refused(tmp_path, text, message):
    with pytest.raises(ProgramFileError, match=message):
        import_time_series(_csv(tmp_path, text))


# --------------------------------------------------- validation of points


def _series_program(points, step_ms=10):
    return Program("p", "", step_ms, [Channel(1, 50, 0, 20, points)])


def test_points_over_the_limit_are_summarized_in_one_line(engine):
    points = [TimeSeriesPoint(k * 0.01, 50, 25 + k) for k in range(10)]  # 25..34 mA
    result = engine.validate(_series_program(points))
    assert result.failed_parameters == [
        "Channel 1 amplitude goes above the 30 mA limit at 4 time-series points "
        "(highest 34 mA at t = 0.09 s)."
    ]


def test_points_below_the_minimum(engine):
    points = [TimeSeriesPoint(0, 50, 1), TimeSeriesPoint(0.01, 10, 1)]
    result = engine.validate(_series_program(points))
    assert result.failed_parameters == [
        "Channel 1 pulse width goes below the 20 µs minimum at 1 time-series point "
        "(lowest 10 µs at t = 0.01 s)."
    ]


def test_out_of_order_times(engine):
    points = [TimeSeriesPoint(0, 50, 1), TimeSeriesPoint(0.02, 50, 1), TimeSeriesPoint(0.01, 50, 1)]
    result = engine.validate(_series_program(points))
    assert any("out of order at point 3" in p for p in result.failed_parameters)


def test_uneven_spacing(engine):
    points = [TimeSeriesPoint(0, 50, 1), TimeSeriesPoint(0.01, 50, 1), TimeSeriesPoint(0.035, 50, 1)]
    result = engine.validate(_series_program(points))
    assert result.failed_parameters == [
        "Channel 1 time-series points are not one 10 ms time step apart "
        "(gap of 25 ms before t = 0.035 s)."
    ]


def test_missing_values_in_points(engine):
    points = [TimeSeriesPoint(0, 50, 1), TimeSeriesPoint(0.01, 50, None), TimeSeriesPoint(None, 50, 1)]
    result = engine.validate(_series_program(points))
    assert "Channel 1 time-series amplitude is missing at 1 time-series point (first at point 2)." in result.failed_parameters
    assert any("time is missing or not a number" in p for p in result.failed_parameters)


def test_client_example_fails_the_placeholder_limits():
    result = ValidationEngine().validate(import_time_series(SAMPLES / "client_example_25ma.mat"))
    assert not result.is_valid
    text = " ".join(result.failed_parameters)
    assert "Time step 1 ms is below" in text
    assert "amplitude goes above" in text


# ----------------------------------------------- saving and opening


def test_imported_program_saves_and_loads_back_identical(tmp_path):
    manager = ProgramFileManager(ValidationEngine(TEST_RANGES))
    program = import_time_series(SAMPLES / "ramp_2ch.mat")
    saved = manager.save(program, tmp_path / "ramp.json")
    loaded = manager.load(saved)
    assert loaded.to_dict() == program.to_dict()
    data = json.loads(saved.read_text(encoding="utf-8"))
    assert len(data["channels"][0]["time_series"]) == 201


def test_constant_programs_still_save_without_a_time_series_key(tmp_path):
    manager = ProgramFileManager(ValidationEngine(TEST_RANGES))
    program = Program("c", "", 50, [Channel(1, 50, 1, 20)])
    data = json.loads(manager.save(program, tmp_path / "c.json").read_text(encoding="utf-8"))
    assert "time_series" not in data["channels"][0]


def test_damaged_time_series_in_json_is_refused(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text(json.dumps({
        "format_version": 1, "name": "bad", "time_step_ms": 10,
        "channels": [{"channel": 1, "pulse_width_us": 50, "amplitude_ma": 1, "frequency_hz": 20,
                      "time_series": [{"time_s": 0, "pulse_width_us": 50}]}],
    }), encoding="utf-8")
    with pytest.raises(ProgramFileError, match="time-series point 1 amplitude is missing"):
        ProgramFileManager(ValidationEngine(TEST_RANGES)).load(path)


def test_file_manager_open_imports_mat_and_validates():
    opened = ProgramFileManager(ValidationEngine(TEST_RANGES)).open(SAMPLES / "ramp_2ch.mat")
    assert opened.validation.is_valid
    assert opened.path.name == "ramp_2ch.mat"


# ----------------------------------------------------- Main Menu and CLI


@pytest.fixture(scope="module")
def app():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    widgets = pytest.importorskip("PySide6.QtWidgets")
    return widgets.QApplication.instance() or widgets.QApplication([])


def test_main_menu_opens_a_mat_file(app, tmp_path):
    from ui.main_menu import MainMenuWindow

    with patch("ui.main_menu.RECENT_PROGRAMS_FILE", tmp_path / "recent.json"):
        window = MainMenuWindow(ProgramFileManager(ValidationEngine(TEST_RANGES)))
        assert window.open_program_file(SAMPLES / "ramp_2ch.mat")
        panel = window.program_panel
        assert panel.table.rowCount() == 2
        assert panel.table.item(0, 2).text() == "0 – 2.5"     # amplitude over time
        assert panel.table.item(0, 1).text() == "50"          # constant pulse width
        assert panel.time_series_label.text().startswith("Time series: 201 points per channel, 0 – 4 s, 20 ms step")
        assert panel.validation_label.text() == "Validation: Passed"
        assert window.recent_list.count() == 1
        window.close()


def test_main_menu_marks_out_of_range_time_series(app, tmp_path):
    from ui.main_menu import MainMenuWindow

    with patch("ui.main_menu.RECENT_PROGRAMS_FILE", tmp_path / "recent.json"):
        window = MainMenuWindow(ProgramFileManager(ValidationEngine()))  # placeholder limits
        assert window.open_program_file(SAMPLES / "client_example_25ma.mat")
        assert "out of range" in window.program_panel.table.item(0, 2).text()
        assert window.program_panel.validation_label.text().startswith("Validation: Failed")
        window.close()


def test_main_menu_refuses_a_bad_import_and_keeps_the_previous_program(app, tmp_path):
    from ui.main_menu import MainMenuWindow

    with patch("ui.main_menu.RECENT_PROGRAMS_FILE", tmp_path / "recent.json"), \
            patch("ui.main_menu.QMessageBox.warning") as warning:
        window = MainMenuWindow(ProgramFileManager(ValidationEngine(TEST_RANGES)))
        window.open_program_file(SAMPLES / "ramp_2ch.mat")
        assert not window.open_program_file(SAMPLES / "missing_frequency.mat")
        assert "frequency" in warning.call_args[0][2]
        assert window.program_panel.opened.path.name == "ramp_2ch.mat"
        window.close()


def test_validation_command_reads_mat_and_csv(capsys):
    from validation.__main__ import main

    code = main([str(SAMPLES / "ramp_2ch.mat"), str(SAMPLES / "ramp_2ch.csv"),
                 str(SAMPLES / "missing_frequency.mat")])
    out = capsys.readouterr().out
    assert code == 1
    assert "ramp_2ch.mat (Two channel ramp (demo)): PASSED" in out
    assert "ramp_2ch.csv (ramp_2ch): PASSED" in out
    assert "missing_frequency.mat: COULD NOT IMPORT" in out
