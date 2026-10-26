"""Opened Program panel on the Main Menu: every sample shows its channels and
validation result, the unsafe sample lists its failing values, and a damaged
file shows an error without changing what is on screen. Runs off-screen.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PySide6.QtWidgets import QApplication  # noqa: E402

from files import ProgramFileManager  # noqa: E402
from ui.main_menu import MainMenuWindow  # noqa: E402
from validation import RangeTable, ValidationEngine  # noqa: E402

SAMPLES = ROOT / "samples"

# Same numbers as the committed placeholders, fixed here so the expected
# messages don't change when the real limits arrive.
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
def window(app, tmp_path):
    with patch("ui.main_menu.RECENT_PROGRAMS_FILE", tmp_path / "recent_programs.json"):
        win = MainMenuWindow(ProgramFileManager(ValidationEngine(TEST_RANGES)))
        yield win
        win.close()


@pytest.fixture
def warnings():
    with patch("ui.main_menu.QMessageBox.warning") as warning:
        yield warning


def cell(window, row, column):
    return window.program_panel.table.item(row, column).text()


def rows(window):
    table = window.program_panel.table
    return [[cell(window, r, c) for c in range(table.columnCount())] for r in range(table.rowCount())]


def test_panel_starts_empty(window):
    panel = window.program_panel
    assert panel.opened is None
    assert "No program open" in panel.name_label.text()
    assert panel.table.isHidden()


def test_one_channel_sample(window):
    assert window.open_program_file(SAMPLES / "valid_1_channel.json")
    panel = window.program_panel
    assert "Single channel test" in panel.name_label.text()
    assert rows(window) == [["1", "50", "1", "20"]]
    assert panel.validation_label.text() == "Validation: Passed"
    assert panel.problems_label.isHidden()


def test_four_channel_sample(window):
    assert window.open_program_file(SAMPLES / "valid_4_channel.json")
    assert rows(window) == [
        ["1", "50", "1", "20"],
        ["2", "60", "1.5", "25"],
        ["3", "40", "0.5", "20"],
        ["4", "80", "2", "30"],
    ]
    assert window.program_panel.validation_label.text() == "Validation: Passed"


def test_unsafe_sample_lists_failing_values(window):
    assert window.open_program_file(SAMPLES / "unsafe_amplitude.json")
    panel = window.program_panel
    assert panel.validation_label.text() == "Validation: Failed (1 problem)"
    assert not panel.problems_label.isHidden()
    assert "Channel 2 amplitude 40 mA is above the 3 mA limit." in panel.problems_label.text()
    # The bad cell is marked in words, not only in red; the good ones are not.
    assert cell(window, 1, 2).startswith("40") and "out of range" in cell(window, 1, 2)
    assert "out of range" not in cell(window, 0, 2)
    assert "out of range" not in cell(window, 1, 1)


def test_panel_is_read_only(window):
    from PySide6.QtWidgets import QAbstractItemView

    window.open_program_file(SAMPLES / "valid_1_channel.json")
    assert window.program_panel.table.editTriggers() == QAbstractItemView.NoEditTriggers


@pytest.mark.parametrize("name", ["missing_amplitude.json", "truncated.json"])
def test_damaged_file_shows_error_and_keeps_previous_program(window, warnings, name):
    window.open_program_file(SAMPLES / "valid_4_channel.json")
    before = rows(window)

    assert window.open_program_file(SAMPLES / "damaged" / name) is False

    warnings.assert_called_once()
    title, text = warnings.call_args.args[1:3]
    assert title == "Could not open program"
    assert name in text
    # Nothing was half-loaded: the 4-channel program is still on screen.
    assert window.program_panel.opened.program.name == "Four channel test"
    assert rows(window) == before
    assert window.recent_list.count() == 1


def test_damaged_file_on_empty_panel_leaves_it_empty(window, warnings):
    assert window.open_program_file(SAMPLES / "damaged" / "truncated.json") is False
    assert window.program_panel.opened is None
    assert window.recent_list.count() == 0


def test_opening_adds_to_recent_and_open_selected_reopens_it(window):
    window.open_program_file(SAMPLES / "unsafe_amplitude.json")
    window.open_program_file(SAMPLES / "valid_1_channel.json")
    assert window.recent_list.count() == 2
    assert "Single channel test" in window.recent_list.item(0).text()

    window.recent_list.setCurrentRow(1)
    window._open_selected_program()
    assert window.program_panel.opened.program.name == "Unsafe amplitude (demo)"
    assert "Failed" in window.program_panel.validation_label.text()


def test_open_selected_with_missing_file_shows_error(window, warnings, tmp_path):
    copy = tmp_path / "gone.json"
    copy.write_text((SAMPLES / "valid_1_channel.json").read_text(encoding="utf-8"), encoding="utf-8")
    window.open_program_file(copy)
    copy.unlink()

    window.recent_list.setCurrentRow(0)
    window._open_selected_program()
    warnings.assert_called_once()
    assert "File not found" in warnings.call_args.args[2]


def test_import_button_opens_chosen_file(window):
    chosen = (str(SAMPLES / "valid_4_channel.json"), "")
    with patch("ui.main_menu.QFileDialog.getOpenFileName", return_value=chosen):
        window.import_button.click()
    assert len(window.program_panel.opened.program.channels) == 4


def test_import_cancelled_changes_nothing(window):
    with patch("ui.main_menu.QFileDialog.getOpenFileName", return_value=("", "")):
        window.import_button.click()
    assert window.program_panel.opened is None
