"""Prof. LaMack's layout: one variable per channel and parameter
(t, pw1, a1, freq1, pw2, a2, freq2, ...), from .mat, .txt or .csv, in
seconds / amps / Hz by default, with frequency allowed to change over time.
Also checks that a frequency that changes over time is validated, saved and
sent to the WSS step by step."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

np = pytest.importorskip("numpy")
scipy_io = pytest.importorskip("scipy.io")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from channels.program_runner import build_frames  # noqa: E402
from files import (  # noqa: E402
    Channel,
    Program,
    ProgramFileError,
    ProgramFileManager,
    TimeSeriesPoint,
    import_time_series,
)
from files.stim_matrix import matrix_variables  # noqa: E402
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
def manager():
    return ProgramFileManager(ValidationEngine(TEST_RANGES))


def lamack_vars(n=11, step=0.001):
    """Same shape as the email: t in s, pw in s, a in A, freq in Hz."""
    t = np.round(np.arange(n) * step, 6)
    return dict(
        t=t,
        pw1=np.full(n, 0.0001),                      # 100 µs
        a1=np.linspace(0, 0.002, n),                 # 0 -> 2 mA
        freq1=np.linspace(20, 30, n),                # changes over time
        pw2=np.full(n, 0.00005),                     # 50 µs
        a2=np.full(n, 0.0015),                       # 1.5 mA
        freq2=np.full(n, 25.0),                      # constant
    )


def write_mat(path, **variables):
    scipy_io.savemat(path, variables, format="5")
    return path


def write_txt(path, variables):
    lines = []
    for name, value in variables.items():
        if isinstance(value, str):
            lines.append(f"{name} = {value}")
        else:
            lines.append(f"{name} = " + ", ".join(f"{v:g}" for v in np.ravel(value)))
    path.write_text("\n".join(lines) + "\n")
    return path


def check_lamack(program, n=11):
    assert [c.number for c in program.channels] == [1, 2]
    ch1, ch2 = program.channels
    assert len(ch1.time_series) == n
    assert program.time_step_ms == pytest.approx(1.0)
    last = ch1.time_series[-1]
    assert last.time_s == pytest.approx(0.01)
    assert last.pulse_width_us == pytest.approx(100.0)       # 0.0001 s
    assert last.amplitude_ma == pytest.approx(2.0)           # 0.002 A
    assert last.frequency_hz == pytest.approx(30.0)          # its own frequency
    assert ch1.frequency_hz == pytest.approx(20.0)           # first value
    assert ch2.time_series[3].pulse_width_us == pytest.approx(50.0)
    assert ch2.time_series[3].amplitude_ma == pytest.approx(1.5)
    assert ch2.frequency_hz == pytest.approx(25.0)
    assert ch2.time_series[3].frequency_hz is None           # constant: kept on the channel


# ------------------------------------------------------------- formats


def test_mat_in_the_layout_from_the_email(manager, tmp_path):
    opened = manager.open(write_mat(tmp_path / "lamack.mat", **lamack_vars()))
    check_lamack(opened.program)
    assert "seconds" in opened.program.description and "amps" in opened.program.description
    assert opened.validation.is_valid, opened.validation.failed_parameters


def test_column_vectors_as_matlab_saves_them(tmp_path):
    variables = {k: np.asarray(v).reshape(-1, 1) for k, v in lamack_vars().items()}
    check_lamack(import_time_series(write_mat(tmp_path / "cols.mat", **variables)))


def test_txt_with_name_equals_values_lines(manager, tmp_path):
    path = write_txt(tmp_path / "lamack.txt", lamack_vars())
    opened = manager.open(path)
    check_lamack(opened.program)
    assert opened.validation.is_valid


def test_txt_lines_can_wrap_and_have_comments_and_brackets(tmp_path):
    path = tmp_path / "wrapped.txt"
    path.write_text(
        "% exported from MATLAB\n"
        "name = Wrist ramp\n"
        "t = [0.000, 0.001,\n"
        "     0.002]\n"
        "pw1 = 0.0001   # seconds\n"
        "a1 = 0; 0.001; 0.002\n"
        "freq1 = 20\n"
    )
    program = import_time_series(path)
    assert program.name == "Wrist ramp"
    ch = program.channels[0]
    assert [p.time_s for p in ch.time_series] == [0.0, 0.001, 0.002]
    assert [p.amplitude_ma for p in ch.time_series] == pytest.approx([0, 1, 2])
    assert all(p.pulse_width_us == pytest.approx(100) for p in ch.time_series)
    assert ch.frequency_hz == 20


@pytest.mark.parametrize("separator", [",", "\t", " "])
def test_txt_table_with_a_header_row(tmp_path, separator):
    v = lamack_vars()
    names = list(v)
    lines = [separator.join(names)]
    lines += [separator.join(f"{v[k][i]:g}" for k in names) for i in range(len(v["t"]))]
    path = tmp_path / "table.txt"
    path.write_text("\n".join(lines) + "\n")
    check_lamack(import_time_series(path))


def test_csv_with_the_same_names(tmp_path):
    v = lamack_vars()
    names = list(v)
    rows = [",".join(names)] + [",".join(f"{v[k][i]:g}" for k in names) for i in range(len(v["t"]))]
    path = tmp_path / "lamack.csv"
    path.write_text("\n".join(rows) + "\n")
    check_lamack(import_time_series(path))


def test_committed_samples(manager):
    for name in ("per_channel_2ch.mat", "per_channel_2ch.txt"):
        opened = manager.open(SAMPLES / name)
        assert [c.number for c in opened.program.channels] == [1, 2]
        assert any(p.frequency_hz is not None for p in opened.program.channels[0].time_series)


# ------------------------------------------------------------- units


def test_units_us_ma_reads_the_apps_units(tmp_path):
    v = dict(t=np.array([0, 0.02]), pw1=np.array([50.0, 60.0]), a1=np.array([1.0, 2.0]),
             freq1=np.array([20.0]), units="us_mA")
    ch = import_time_series(write_mat(tmp_path / "app.mat", **v)).channels[0]
    assert [p.pulse_width_us for p in ch.time_series] == [50, 60]
    assert [p.amplitude_ma for p in ch.time_series] == [1, 2]


def test_unit_suffix_on_a_name_wins(tmp_path):
    v = dict(t=np.array([0, 0.02]), pw1_us=np.array([50.0, 60.0]), a1_ma=np.array([1.0, 2.0]),
             freq1=np.array([20.0]), pw2_ms=np.array([0.05]), a2_ua=np.array([500.0]),
             freq2_hz=np.array([25.0]))
    program = import_time_series(write_mat(tmp_path / "suffix.mat", **v))
    ch1, ch2 = program.channels
    assert ch1.time_series[1].pulse_width_us == 60 and ch1.time_series[1].amplitude_ma == 2
    assert ch2.time_series[0].pulse_width_us == pytest.approx(50)    # 0.05 ms
    assert ch2.time_series[0].amplitude_ma == pytest.approx(0.5)     # 500 µA


def test_csv_style_names_are_accepted_in_a_mat_file(tmp_path):
    v = dict(t=np.array([0, 0.02]), ch1_pulse_width_us=np.array([50.0]),
             ch1_amplitude_ma=np.array([1.0, 2.0]), ch1_frequency_hz=np.array([20.0, 30.0]))
    ch = import_time_series(write_mat(tmp_path / "csvnames.mat", **v)).channels[0]
    assert [p.frequency_hz for p in ch.time_series] == [20, 30]


def test_values_too_big_for_seconds_or_amps_are_refused_not_converted(tmp_path):
    """50 (µs) read as seconds would be 50 s: a unit mix-up, so refuse."""
    v = dict(t=np.array([0, 0.02]), pw1=np.array([50.0]), a1=np.array([2.0]), freq1=np.array([20.0]))
    with pytest.raises(ProgramFileError) as info:
        import_time_series(write_mat(tmp_path / "mixed.mat", **v))
    text = str(info.value)
    assert "pw1 goes up to 50, which read as seconds is more than 10 ms" in text
    assert "a1 goes up to 2, which read as amps is more than 100 mA" in text
    assert "units = 'us_mA'" in text


# ------------------------------------------------------------- refused


@pytest.mark.parametrize("change, message", [
    ({"freq2": None}, "Channel 2 is missing freq2"),
    ({"t": None}, "Time is missing"),
    ({"a1": np.zeros(7)}, "a1 has 7 values but t has 11"),
    ({"pw1": np.array([0.0001, np.nan] * 5 + [0.0001])}, "pw1 has empty (NaN) or infinite values"),
    ({"pw1_us": np.array([50.0])}, "Channel 1 pulse width is given twice"),
    ({"units": "volts"}, "units = 'volts' isn't recognized"),
    ({"a1": np.ones((11, 2))}, "a1 must be a single row or column"),
])
def test_bad_files_are_refused_with_a_reason(tmp_path, change, message):
    v = lamack_vars()
    for key, value in change.items():
        if value is None:
            v.pop(key)
        else:
            v[key] = value
    with pytest.raises(ProgramFileError) as info:
        import_time_series(write_mat(tmp_path / "bad.mat", **v))
    assert message in str(info.value)
    assert "nothing was loaded" in str(info.value)


def test_txt_with_dots_instead_of_numbers_is_refused(tmp_path):
    path = tmp_path / "dots.txt"
    path.write_text("t = 0.000, 0.001, ...., 10.000\npw1 = 0.001\na1 = 0\nfreq1 = 20\n")
    with pytest.raises(ProgramFileError, match="every value must be written out"):
        import_time_series(path)


def test_txt_with_words_in_the_numbers_is_refused(tmp_path):
    path = tmp_path / "words.txt"
    path.write_text("t = 0, 0.001\npw1 = 0.0001, blah\na1 = 0\nfreq1 = 20\n")
    with pytest.raises(ProgramFileError, match="pw1: 'blah' is not a number"):
        import_time_series(path)


# ------------------------------------------------- frequency over time


def test_frequency_over_time_is_validated_at_every_step(manager, tmp_path):
    v = lamack_vars()
    v["freq1"] = np.where(v["t"] > 0.005, 150.0, 20.0)
    opened = manager.open(write_mat(tmp_path / "fast.mat", **v))
    assert not opened.validation.is_valid
    text = " ".join(opened.validation.failed_parameters)
    assert "Channel 1 frequency goes above the 100 Hz limit at 5 time-series points" in text
    assert "highest 150 Hz at t = 0.006 s" in text


def test_runner_sends_each_steps_frequency(tmp_path):
    program = import_time_series(write_mat(tmp_path / "f.mat", **lamack_vars()))
    frames = build_frames(program)
    assert frames[0].commands[0].frequency_hz == pytest.approx(20)
    assert frames[-1].commands[0].frequency_hz == pytest.approx(30)
    assert frames[0].commands[0].ipi_ms == 50 and frames[-1].commands[0].ipi_ms == 33
    assert {f.commands[1].frequency_hz for f in frames} == {25}


def test_saved_json_keeps_frequency_per_step_and_old_files_are_unchanged(manager, tmp_path):
    program = import_time_series(write_mat(tmp_path / "f.mat", **lamack_vars()))
    data = program.to_dict()
    assert data["channels"][0]["time_series"][-1]["frequency_hz"] == pytest.approx(30)
    assert "frequency_hz" not in data["channels"][1]["time_series"][0]
    path = tmp_path / "saved.json"
    path.write_text(json.dumps(data))
    reopened = manager.open(path).program
    assert reopened.channels[0].time_series[-1].frequency_hz == pytest.approx(30)

    plain = TimeSeriesPoint(time_s=0, pulse_width_us=50, amplitude_ma=1)
    assert plain.to_dict() == {"time_s": 0, "pulse_width_us": 50, "amplitude_ma": 1}


def test_bad_frequency_in_a_saved_point_is_a_damaged_file(manager, tmp_path):
    path = tmp_path / "bad.json"
    path.write_text(json.dumps({
        "format_version": 1, "name": "x", "description": "", "time_step_ms": 10,
        "channels": [{"channel": 1, "pulse_width_us": 50, "amplitude_ma": 1, "frequency_hz": 20,
                      "time_series": [{"time_s": 0, "pulse_width_us": 50, "amplitude_ma": 1,
                                       "frequency_hz": "fast"}]}],
    }))
    with pytest.raises(ProgramFileError, match="frequency 'fast' is not a number"):
        manager.open(path)


def test_stim_matrix_frequency_may_change_and_export_keeps_it(tmp_path):
    rows = 11
    stim = np.column_stack([np.full(rows, 50.0), np.full(rows, 1.0), np.linspace(20, 30, rows)])
    path = write_mat(tmp_path / "m.mat", stim=stim, total_time_s=0.1, num_channels=1.0, time_step_ms=10.0)
    program = import_time_series(path)
    assert program.channels[0].time_series[-1].frequency_hz == pytest.approx(30)
    exported = matrix_variables(program)["stim"]
    assert exported[:, 2] == pytest.approx(np.linspace(20, 30, rows))


def test_csv_frequency_may_change(tmp_path):
    path = tmp_path / "f.csv"
    path.write_text("time_s,ch1_amplitude_ma,ch1_pulse_width_us,ch1_frequency_hz\n"
                    "0,1,50,20\n0.01,1,50,30\n")
    ch = import_time_series(path).channels[0]
    assert [p.frequency_hz for p in ch.time_series] == [20, 30]


# ------------------------------------------------------------- screen


def test_main_menu_shows_the_frequency_range(tmp_path):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PySide6.QtWidgets")
    from PySide6.QtWidgets import QApplication

    from ui.main_menu import MainMenuWindow

    QApplication.instance() or QApplication([])
    path = write_mat(tmp_path / "lamack.mat", **lamack_vars())
    with patch("ui.main_menu.RECENT_PROGRAMS_FILE", tmp_path / "recent.json"):
        window = MainMenuWindow(ProgramFileManager(ValidationEngine(TEST_RANGES)))
        try:
            assert window.open_program_file(path)
            table = window.program_panel.table
            row1 = [table.item(0, c).text() for c in range(table.columnCount())]
            assert row1 == ["1", "100", "0 – 2", "20 – 30"]
            assert "frequency show the lowest – highest" in window.program_panel.time_series_label.text()
        finally:
            window.close()
