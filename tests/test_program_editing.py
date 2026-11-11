"""Editing an opened program on the Main Menu: values change in the app and
in the file straight away, unsafe values are never written, and imports
are saved with "Save as JSON". Every test edits a copy, never the samples.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication, QStyleOptionViewItem  # noqa: E402

from comms import FakeCommunicationAdapter  # noqa: E402
from files import ProgramFileManager  # noqa: E402
from ui.main_menu import MainMenuWindow  # noqa: E402
from ui.program_panel import VALUE_ROLE  # noqa: E402
from validation import RangeTable, ValidationEngine  # noqa: E402

SAMPLES = ROOT / "samples"
PW, AMP, FREQ = 1, 2, 3  # table columns

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


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def manager():
    return ProgramFileManager(ValidationEngine(TEST_RANGES))


@pytest.fixture
def window(app, tmp_path, manager):
    with patch("ui.main_menu.RECENT_PROGRAMS_FILE", tmp_path / "recent_programs.json"):
        win = MainMenuWindow(manager, FakeCommunicationAdapter())
        yield win
        win.close()


def copy_of(name: str, tmp_path: Path) -> Path:
    folder = tmp_path / "programs"
    folder.mkdir(exist_ok=True)
    target = folder / Path(name).name
    shutil.copy(SAMPLES / name, target)
    return target


def edit(window, row, column, value):
    """Change a cell the way the spin box does when the user presses Enter."""
    window.program_panel.table.item(row, column).setData(VALUE_ROLE, value)


def on_disk(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def panel(window):
    return window.program_panel


# ------------------------------------------------------------- live save

def test_edit_changes_app_and_file_straight_away(window, tmp_path):
    path = copy_of("valid_4_channel.json", tmp_path)
    window.open_program_file(path)

    edit(window, 1, AMP, 2.25)

    assert panel(window).opened.program.channels[1].amplitude_ma == 2.25
    assert panel(window).table.item(1, AMP).text() == "2.25"
    assert on_disk(path)["channels"][1]["amplitude_ma"] == 2.25
    assert panel(window).save_status_label.text().startswith(f"Saved to {path.name}")
    assert panel(window).validation_label.text() == "Validation: Passed"


def test_every_value_can_be_edited_without_a_new_file(window, tmp_path):
    path = copy_of("valid_1_channel.json", tmp_path)
    window.open_program_file(path)

    edit(window, 0, PW, 70)
    edit(window, 0, AMP, 0.5)
    edit(window, 0, FREQ, 35)
    panel(window).time_step_box.setValue(100)

    channel = on_disk(path)["channels"][0]
    assert (channel["pulse_width_us"], channel["amplitude_ma"], channel["frequency_hz"]) == (70, 0.5, 35)
    assert on_disk(path)["time_step_ms"] == 100
    assert [p.name for p in path.parent.iterdir()] == ["valid_1_channel.json"]  # no new files


def test_whole_numbers_stay_whole_in_the_file(window, tmp_path):
    path = copy_of("valid_1_channel.json", tmp_path)
    window.open_program_file(path)
    edit(window, 0, PW, 70.0)            # spin boxes hand back floats
    assert '"pulse_width_us": 70,' in path.read_text(encoding="utf-8")


def test_editing_through_the_real_spin_box_editor(window, tmp_path):
    path = copy_of("valid_1_channel.json", tmp_path)
    window.open_program_file(path)
    table = panel(window).table
    index = table.model().index(0, AMP)
    delegate = table.itemDelegate()

    editor = delegate.createEditor(table.viewport(), QStyleOptionViewItem(), index)
    delegate.setEditorData(editor, index)
    assert editor.value() == 1.0 and editor.decimals() == 2
    editor.setValue(1.75)
    delegate.setModelData(editor, table.model(), index)

    assert on_disk(path)["channels"][0]["amplitude_ma"] == 1.75


# ------------------------------------------------------------- safety

def test_unsafe_edit_is_shown_but_never_written(window, tmp_path):
    path = copy_of("valid_1_channel.json", tmp_path)
    window.open_program_file(path)
    before = path.read_bytes()

    edit(window, 0, AMP, 40)

    assert path.read_bytes() == before
    assert "out of range" in panel(window).table.item(0, AMP).text()
    assert "Channel 1 amplitude 40 mA is above the 3 mA limit." in panel(window).problems_label.text()
    assert panel(window).save_status_label.text().startswith("Not saved")
    assert not window.run_button.isEnabled()


def test_fixing_the_unsafe_sample_saves_it(window, tmp_path):
    path = copy_of("unsafe_amplitude.json", tmp_path)
    window.open_program_file(path)
    assert panel(window).validation_label.text().startswith("Validation: Failed")

    edit(window, 1, AMP, 2)

    assert panel(window).validation_label.text() == "Validation: Passed"
    assert on_disk(path)["channels"][1]["amplitude_ma"] == 2
    assert ProgramFileManager(ValidationEngine(TEST_RANGES)).open(path).validation.is_valid


def test_run_screen_keeps_the_program_it_was_opened_with(window, tmp_path):
    path = copy_of("valid_1_channel.json", tmp_path)
    window.open_program_file(path)
    window.open_execution_screen()
    running = window.execution_window.opened.program

    edit(window, 0, AMP, 2.5)

    assert running.channels[0].amplitude_ma == 1.0
    assert panel(window).opened.program.channels[0].amplitude_ma == 2.5


# ------------------------------------------------------------- imports

def test_imported_time_series_is_edited_in_app_and_saved_as_json(window, tmp_path):
    source = SAMPLES / "matlab" / "ramp_2ch.csv"
    window.open_program_file(source)
    table = panel(window).table
    # Values that change over time can't be typed over; frequency can.
    assert not table.item(0, AMP).flags() & Qt.ItemIsEditable
    assert table.item(0, FREQ).flags() & Qt.ItemIsEditable
    assert not panel(window).time_step_box.isEnabled()

    before = source.read_bytes()
    edit(window, 0, FREQ, 30)
    assert source.read_bytes() == before
    assert "Use Save as JSON" in panel(window).save_status_label.text()

    target = tmp_path / "ramp_copy"
    with patch("ui.program_panel.QFileDialog.getSaveFileName", return_value=(str(target), "")):
        panel(window).save_as_button.click()

    saved = target.with_suffix(".json")
    assert on_disk(saved)["channels"][0]["frequency_hz"] == 30
    assert panel(window).opened.path == saved
    assert str(saved.resolve()) in [p.get("file_path") for p in window._recent_programs]

    edit(window, 0, FREQ, 31)                       # now it saves live
    assert on_disk(saved)["channels"][0]["frequency_hz"] == 31
