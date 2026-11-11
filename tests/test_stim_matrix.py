"""The MATLAB "stim matrix" layout: rows = total_time / time_step + 1,
columns = active channels x stimulation parameters. Import, export, and the
New Program screen's total time / active channels / ramps.
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest
from scipy.io import loadmat, savemat

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PySide6.QtWidgets import QApplication  # noqa: E402

import editor.new_program_window as npw  # noqa: E402
from files import ProgramFileError, ProgramFileManager  # noqa: E402
from files.stim_matrix import export_mat, matrix_variables  # noqa: E402
from validation import RangeTable, ValidationEngine  # noqa: E402

SAMPLES = ROOT / "samples"

TEST_RANGES = RangeTable.from_dict({
    "source": "test limits",
    "confirmed": True,
    "parameters": {
        "pulse_width": {"label": "pulse width", "unit": "µs", "min": 20, "max": 100},
        "amplitude": {"label": "amplitude", "unit": "mA", "min": 0, "max": 3},
        "frequency": {"label": "frequency", "unit": "Hz", "min": 1, "max": 50},
        "time_step": {"label": "time step", "unit": "ms", "min": 10, "max": 1000},
    },
})


@pytest.fixture
def manager():
    return ProgramFileManager(ValidationEngine(TEST_RANGES))


def client_file(tmp_path, name="client.mat", channels=3, total=2.0, step_ms=20.0, **extra):
    """What a client MATLAB script writes: pulse width + amplitude per channel."""
    rows = int(round(total * 1000 / step_ms)) + 1
    t = np.arange(rows) * step_ms / 1000
    columns = []
    for ch in range(channels):
        columns += [np.full(rows, 50.0 + ch), np.round(np.clip(t / total, 0, 1) * (ch + 1) * 0.5, 4)]
    data = {"stim": np.column_stack(columns), "total_time_s": total, "num_channels": float(channels),
            "time_step_ms": step_ms, "frequency_hz": 20.0}
    data.update(extra)
    data = {k: v for k, v in data.items() if v is not None}
    path = tmp_path / name
    savemat(path, data, format="5")
    return path


# ------------------------------------------------------------- import

def test_client_layout_imports_as_time_series(manager, tmp_path):
    opened = manager.open(client_file(tmp_path))
    program = opened.program
    assert program.time_step_ms == 20.0
    assert [c.number for c in program.channels] == [1, 2, 3]
    for k, channel in enumerate(program.channels):
        assert len(channel.time_series) == 101                    # 2 s / 20 ms + 1
        assert channel.frequency_hz == 20.0
        assert channel.time_series[0].pulse_width_us == 50 + k
        assert channel.time_series[-1].time_s == 2.0
        assert channel.time_series[-1].amplitude_ma == pytest.approx((k + 1) * 0.5)
    assert opened.validation.is_valid


def test_time_step_can_be_left_out(manager, tmp_path):
    program = manager.open(client_file(tmp_path, time_step_ms=None)).program
    assert program.time_step_ms == pytest.approx(20.0)


def test_time_step_in_seconds(manager, tmp_path):
    path = client_file(tmp_path, time_step_ms=None, time_step_s=0.02)
    assert manager.open(path).program.time_step_ms == pytest.approx(20.0)


def test_three_parameters_per_channel_include_frequency(manager, tmp_path):
    rows = 11
    stim = np.column_stack([np.full(rows, 40.0), np.full(rows, 1.0), np.full(rows, 25.0)] * 2)
    path = tmp_path / "three.mat"
    savemat(path, {"stim": stim, "total_time_s": 1.0, "num_channels": 2.0, "time_step_ms": 100.0})
    program = manager.open(path).program
    assert [c.frequency_hz for c in program.channels] == [25.0, 25.0]


def test_one_parameter_is_amplitude_and_the_rest_come_from_variables(manager, tmp_path):
    stim = np.linspace(0, 2, 11).reshape(-1, 1)
    path = tmp_path / "amp_only.mat"
    savemat(path, {"stim": stim, "total_time_s": 1.0, "num_channels": 1.0,
                   "pulse_width_us": 60.0, "frequency_hz": 30.0})
    channel = manager.open(path).program.channels[0]
    assert channel.time_series[-1].amplitude_ma == 2.0
    assert channel.time_series[5].pulse_width_us == 60.0
    assert channel.frequency_hz == 30.0


def test_parameters_list_sets_the_column_order(manager, tmp_path):
    stim = np.column_stack([np.full(3, 1.5), np.full(3, 70.0)])          # amp, then pw
    path = tmp_path / "ordered.mat"
    savemat(path, {"stim": stim, "total_time_s": 0.2, "num_channels": 1.0,
                   "parameters": np.array(["amp", "pw"], dtype=object), "frequency_hz": 20.0})
    point = manager.open(path).program.channels[0].time_series[0]
    assert (point.amplitude_ma, point.pulse_width_us) == (1.5, 70.0)


def test_columns_grouped_by_parameter(manager, tmp_path):
    # [ch1 pw, ch2 pw, ch1 amp, ch2 amp]
    stim = np.column_stack([np.full(3, 40.0), np.full(3, 80.0), np.full(3, 1.0), np.full(3, 2.0)])
    path = tmp_path / "grouped.mat"
    savemat(path, {"stim": stim, "total_time_s": 0.2, "num_channels": 2.0,
                   "column_order": "parameter", "frequency_hz": 20.0})
    ch1, ch2 = manager.open(path).program.channels
    assert (ch1.pulse_width_us, ch1.amplitude_ma, ch2.pulse_width_us, ch2.amplitude_ma) == (40, 1, 80, 2)


def test_channel_numbers_can_be_given(manager, tmp_path):
    path = tmp_path / "numbers.mat"
    stim = np.column_stack([np.full(3, 50.0), np.full(3, 1.0)] * 2)
    savemat(path, {"stim": stim, "total_time_s": 0.2, "channels": np.array([[2.0, 5.0]]),
                   "frequency_hz": 20.0})
    assert [c.number for c in manager.open(path).program.channels] == [2, 5]


def _variant(tmp_path, **changes):
    stim = np.column_stack([np.full(101, 50.0), np.full(101, 1.0)] * 2)
    data = {"stim": stim, "total_time_s": 2.0, "num_channels": 2.0,
            "time_step_ms": 20.0, "frequency_hz": 20.0}
    data.update(changes)
    path = tmp_path / "variant.mat"
    savemat(path, {k: v for k, v in data.items() if v is not None})
    return path


@pytest.mark.parametrize("changes, message", [
    ({"stim": np.ones((100, 4))}, "stim has 100 rows but total_time_s / time step + 1 = 2 s / 20 ms + 1 = 101"),
    ({"stim": np.ones((101, 5))}, "stim has 5 columns, which isn't a multiple of 2 channels"),
    ({"time_step_ms": 30.0}, "total_time_s (2 s) is not a whole number of 30 ms time steps"),
    ({"total_time_s": None}, "total_time_s is missing"),
    ({"num_channels": None}, "num_channels is missing"),
    ({"num_channels": 2.5}, "num_channels must be a whole number"),
    ({"frequency_hz": None}, "frequency_hz is missing"),
    ({"stim": np.ones((101, 8))}, "4 columns per channel"),
    ({"stim": np.column_stack([np.ones(101), np.ones(101), np.arange(101.0)] * 2)},
     "Channel 1 frequency changes over time"),
    ({"parameters": np.array(["pw", "volts"], dtype=object)}, '"volts" is not a stimulation parameter'),
    ({"stim": np.full((101, 4), np.nan)}, "stim has empty (NaN) or infinite values"),
])
def test_bad_matrix_files_are_refused_with_a_reason(manager, tmp_path, changes, message):
    with pytest.raises(ProgramFileError) as info:
        manager.open(_variant(tmp_path, **changes))
    assert message in str(info.value)
    assert "nothing was loaded" in str(info.value)


def test_committed_sample_imports_and_passes():
    opened = ProgramFileManager().open(SAMPLES / "matlab" / "stim_matrix_3ch.mat")
    assert len(opened.program.channels) == 3
    assert len(opened.program.channels[0].time_series) == 151           # 3 s / 20 ms + 1
    assert opened.validation.is_valid


# ------------------------------------------------------------- export

def test_export_writes_the_same_layout(manager, tmp_path):
    program = manager.open(client_file(tmp_path, channels=2)).program
    variables = matrix_variables(program)
    assert variables["stim"].shape == (101, 6)                            # 2 channels x 3 parameters
    assert variables["total_time_s"] == 2.0 and variables["num_channels"] == 2
    # channel 2's columns: pulse width, amplitude, frequency
    assert variables["stim"][0, 3:6].tolist() == [51.0, 0.0, 20.0]


def test_export_then_import_is_identical(manager, tmp_path):
    program = manager.open(client_file(tmp_path)).program
    export_mat(program, tmp_path / "out.mat")
    back = manager.open(tmp_path / "out.mat").program
    assert back.channels == program.channels
    assert back.time_step_ms == program.time_step_ms
    assert back.name == program.name


def test_exported_file_is_a_plain_matlab_file(manager, tmp_path):
    export_mat(manager.open(client_file(tmp_path)).program, tmp_path / "out.mat")
    raw = loadmat(tmp_path / "out.mat")
    assert raw["stim"].shape == (101, 9)
    assert [str(p[0]) for p in raw["parameters"].reshape(-1)] == ["pulse_width_us", "amplitude_ma", "frequency_hz"]


# ------------------------------------------------------------- New Program screen

@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def editor(app, manager, tmp_path, monkeypatch):
    monkeypatch.setattr(npw, "CONFIRM_DISCARD", False)
    monkeypatch.setattr(npw, "PROGRAMS_FOLDER", tmp_path / "programs")
    win = npw.NewProgramWindow(manager)
    win.name_edit.setText("Timed")
    yield win
    win.dirty = False
    win.close()


def test_without_total_time_values_stay_constant(editor):
    assert editor.timing() == (None, None)
    assert editor.program().channels[0].time_series == []
    assert editor.current_canvas().blocks["amplitude"].ramp_box.isHidden()


def test_total_time_gives_rows_per_channel(editor):
    editor.total_time_box.setValue(2.0)                                   # 20 ms step
    editor.time_step_box.setValue(20)
    channel = editor.program().channels[0]
    assert len(channel.time_series) == 101
    assert channel.time_series[-1].time_s == 2.0
    assert "101 time steps" in editor.shape_label.text()
    assert not editor.current_canvas().blocks["amplitude"].ramp_box.isHidden()
    assert editor.current_canvas().blocks["frequency"].ramp_box.isHidden()   # frequency can't ramp
    assert editor.problems == []


def test_ramp_is_a_straight_line_over_the_total_time(editor):
    editor.total_time_box.setValue(1.0)
    editor.time_step_box.setValue(100)                                     # 11 rows
    block = editor.current_canvas().blocks["amplitude"]
    block.set_value(0.5)
    block.set_ramp(2.5)
    amps = [p.amplitude_ma for p in editor.program().channels[0].time_series]
    assert amps[0] == 0.5 and amps[5] == 1.5 and amps[-1] == 2.5


def test_total_time_must_be_whole_time_steps(editor):
    editor.time_step_box.setValue(30)
    editor.total_time_box.setValue(1.0)
    assert any("not a whole number of 30 ms" in p for p in editor.problems)
    assert not editor.save_button.isEnabled() and not editor.export_button.isEnabled()


def test_unsafe_ramp_end_is_caught(editor):
    editor.total_time_box.setValue(1.0)
    editor.current_canvas().blocks["amplitude"].set_ramp(10)
    assert "⚠" in editor.tabs.tabText(0)
    assert any("amplitude" in p and "3 mA" in p for p in editor.problems)
    assert not editor.save_button.isEnabled()


def test_active_channels_box_and_tabs_stay_in_step(editor):
    editor.channel_count_box.setValue(4)
    assert editor.tabs.count() == 4
    editor.channel_count_box.setValue(2)
    assert editor.tabs.count() == 2
    editor.add_tab_button.click()
    assert editor.channel_count_box.value() == 3


def test_duplicate_keeps_the_ramp(editor):
    editor.total_time_box.setValue(1.0)
    editor.current_canvas().blocks["amplitude"].set_ramp(2.0)
    copy = editor.duplicate_channel(0)
    assert copy.blocks["amplitude"].ramps()
    assert copy.blocks["amplitude"].end_value() == 2.0


def test_export_from_new_program_imports_back_identical(editor, manager, tmp_path):
    editor.total_time_box.setValue(2.0)
    editor.time_step_box.setValue(20)
    editor.channel_count_box.setValue(2)
    editor.canvases()[1].add_block("starter")
    editor.current_canvas().blocks["amplitude"].set_ramp(2.0)
    target = tmp_path / "timed.mat"
    with patch("editor.new_program_window.QFileDialog.getSaveFileName", return_value=(str(target), "")):
        assert editor.export_mat() == target

    raw = loadmat(target)
    assert raw["stim"].shape == (101, 6)
    back = manager.open(target).program
    assert back.channels == editor.program().channels


def test_saved_timed_program_loads_back_identical(editor, manager, tmp_path):
    editor.total_time_box.setValue(0.5)
    editor.current_canvas().blocks["pulse_width"].set_ramp(80)
    with patch("editor.new_program_window.QFileDialog.getSaveFileName",
               return_value=(str(tmp_path / "timed.json"), "")):
        assert editor.save()
    assert manager.load(tmp_path / "timed.json") == editor.program()


# ------------------------------------------------------------- samples are kept

def test_editing_a_sample_in_place_never_overwrites_it(app, manager, tmp_path):
    from ui.main_menu import MainMenuWindow
    from ui.program_panel import VALUE_ROLE

    # Pretend tmp_path/samples is the project's samples folder.
    samples = tmp_path / "samples"
    samples.mkdir()
    sample = samples / "valid_1_channel.json"
    shutil.copy(SAMPLES / "valid_1_channel.json", sample)
    before = sample.read_bytes()
    with patch("ui.main_menu.RECENT_PROGRAMS_FILE", tmp_path / "recent.json"), \
            patch("ui.program_panel.SAMPLES_FOLDER", samples), \
            patch("ui.program_panel.PROGRAMS_FOLDER", tmp_path / "programs"):
        menu = MainMenuWindow(manager)
        menu.open_program_file(sample)
        panel = menu.program_panel
        assert panel.save_as_button.text() == "Save a copy..."
        panel.table.item(0, 2).setData(VALUE_ROLE, 2.0)

        assert sample.read_bytes() == before
        assert "is a sample" in panel.save_status_label.text()
        assert panel.opened.program.channels[0].amplitude_ma == 2.0      # still edited in the app

        with patch("ui.program_panel.QFileDialog.getSaveFileName") as dialog:
            dialog.return_value = (str(tmp_path / "programs" / "mine.json"), "")
            assert panel.save_as()
        assert dialog.call_args.args[2] == str(tmp_path / "programs" / "valid_1_channel.json")
        assert manager.load(tmp_path / "programs" / "mine.json").channels[0].amplitude_ma == 2.0
        menu.close()
