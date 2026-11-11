"""New Program screen: blocks dragged or clicked onto channel tabs, tabs
added / duplicated / closed / reordered, live validation, and saving a
program that the Main Menu then opens ready to edit. Runs off-screen.
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

from PySide6.QtCore import QMimeData, QPointF, Qt  # noqa: E402
from PySide6.QtGui import QDropEvent  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

import editor.new_program_window as npw  # noqa: E402
from editor.new_program_window import BLOCK_MIME, NewProgramWindow, STARTER  # noqa: E402
from files import Channel, ProgramFileManager  # noqa: E402
from validation import RangeTable, ValidationEngine  # noqa: E402

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
def window(app, manager, tmp_path, monkeypatch):
    monkeypatch.setattr(npw, "CONFIRM_DISCARD", False)
    monkeypatch.setattr(npw, "PROGRAMS_FOLDER", tmp_path / "programs")
    win = NewProgramWindow(manager)
    yield win
    win.dirty = False
    win.close()


def drop(canvas, key: str) -> None:
    """Drop a palette block on a channel, as a real drag and drop does."""
    mime = QMimeData()
    mime.setData(BLOCK_MIME, key.encode())
    event = QDropEvent(QPointF(20, 20), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)
    canvas.dropEvent(event)


def save_to(window, path: Path) -> bool:
    with patch("editor.new_program_window.QFileDialog.getSaveFileName", return_value=(str(path), "")):
        return window.save()


def tab_titles(window) -> list[str]:
    return [window.tabs.tabText(i) for i in range(window.tabs.count())]


# ------------------------------------------------------------- starting point

def test_starts_with_one_channel_tab_holding_starter_blocks(window):
    assert tab_titles(window) == ["Channel 1"]
    assert window.program().channels == [Channel(1, 50, 1.0, 20)]
    # Only the name is missing, so it can't be saved yet.
    assert window.problems == ["Give the program a name."]
    assert not window.save_button.isEnabled()


def test_naming_it_makes_it_ready_to_save(window):
    window.name_edit.setText("Wrist extension")
    assert window.problems == []
    assert window.save_button.isEnabled()
    assert window.validation_label.text().startswith("Validation: Passed")


# ------------------------------------------------------------- blocks

def test_drag_and_drop_a_block_onto_a_channel(window):
    canvas = window.add_channel()
    assert canvas.blocks == {}
    assert "Channel 2 pulse width is missing." in window.problems

    drop(canvas, "pulse_width")
    assert set(canvas.blocks) == {"pulse_width"}
    assert "Channel 2 pulse width is missing." not in window.problems
    assert "Channel 2 amplitude is missing." in window.problems


def test_starter_block_adds_all_three(window):
    canvas = window.add_channel()
    drop(canvas, STARTER)
    assert set(canvas.blocks) == {"pulse_width", "amplitude", "frequency"}


def test_clicking_a_palette_block_adds_it_to_the_current_tab(window):
    canvas = window.add_channel()
    QTest.mouseClick(window.palette_blocks["amplitude"], Qt.LeftButton)
    assert set(canvas.blocks) == {"amplitude"}


def test_a_channel_holds_one_block_per_value(window):
    canvas = window.current_canvas()
    drop(canvas, "amplitude")
    assert len(canvas.blocks) == 3


def test_removing_a_block_marks_the_tab(window):
    window.name_edit.setText("p")
    canvas = window.current_canvas()
    canvas.blocks["frequency"].remove_button.click()
    assert "frequency" not in canvas.blocks
    assert tab_titles(window) == ["Channel 1  ⚠"]
    assert window.problems == ["Channel 1 frequency is missing."]
    assert not window.save_button.isEnabled()


def test_unsafe_value_is_listed_and_blocks_saving(window):
    window.name_edit.setText("p")
    window.current_canvas().blocks["amplitude"].set_value(40)
    assert window.problems == ["Channel 1 amplitude 40 mA is above the 3 mA limit."]
    assert "⚠" in tab_titles(window)[0]
    assert not window.save_button.isEnabled()
    with patch("editor.new_program_window.QMessageBox.warning") as warning:
        assert window.save() is False
    warning.assert_called_once()


# ------------------------------------------------------------- tabs

def test_plus_button_adds_tabs_with_the_next_free_number(window):
    window.add_tab_button.click()
    window.add_tab_button.click()
    assert tab_titles(window) == ["Channel 1", "Channel 2  ⚠", "Channel 3  ⚠"]
    assert window.tabs.currentIndex() == 2


def test_duplicate_channel_builds_off_an_existing_one(window):
    first = window.current_canvas()
    first.blocks["amplitude"].set_value(2.5)
    copy = window.duplicate_channel(0)
    assert copy.number() == 2
    assert copy.channel() == Channel(2, 50, 2.5, 20)

    copy.blocks["pulse_width"].set_value(80)       # editing the copy...
    assert first.channel().pulse_width_us == 50    # ...leaves the original alone


def test_closing_a_tab_removes_the_channel(window):
    window.duplicate_channel(0)
    window.close_channel(0)
    assert [c.number for c in window.program().channels] == [2]


def test_moving_tabs_reorders_channels(window):
    window.duplicate_channel(0)
    window.tabs.tabBar().moveTab(0, 1)
    assert [c.number for c in window.program().channels] == [2, 1]


def test_changing_the_channel_number_renames_the_tab(window):
    window.current_canvas().number_box.setValue(4)
    assert tab_titles(window) == ["Channel 4"]


def test_duplicate_channel_numbers_are_reported(window):
    window.name_edit.setText("p")
    window.duplicate_channel(0).number_box.setValue(1)
    assert "Channel 1 appears more than once." in window.problems


# ------------------------------------------------------------- saving

def test_save_writes_a_file_that_loads_back_identical(window, manager, tmp_path):
    window.name_edit.setText("Two channels")
    window.description_edit.setText("Built on the New Program screen")
    window.duplicate_channel(0).blocks["frequency"].set_value(30)
    saved = []
    window.program_saved.connect(saved.append)

    assert save_to(window, tmp_path / "two_channels.json")

    path = tmp_path / "two_channels.json"
    assert manager.load(path) == window.program()
    assert saved == [path]
    assert not window.dirty
    assert window.windowTitle() == "COSMIIC - two_channels.json"


def test_later_saves_reuse_the_same_file(window, manager, tmp_path):
    window.name_edit.setText("p")
    save_to(window, tmp_path / "p.json")
    window.current_canvas().blocks["amplitude"].set_value(2)
    assert window.dirty

    with patch("editor.new_program_window.QFileDialog.getSaveFileName") as dialog:
        assert window.save()
    dialog.assert_not_called()
    assert manager.load(tmp_path / "p.json").channels[0].amplitude_ma == 2


def test_cancelled_save_dialog_saves_nothing(window, tmp_path):
    window.name_edit.setText("p")
    with patch("editor.new_program_window.QFileDialog.getSaveFileName", return_value=("", "")):
        assert window.save() is False
    assert window.path is None


def test_suggested_file_name_comes_from_the_program_name():
    assert npw._file_name("Wrist extension #2") == "wrist_extension_2"
    assert npw._file_name("  ") == "new_program"


# ------------------------------------------------------------- Main Menu

def test_new_program_button_opens_the_screen_and_saved_program_opens_on_the_menu(
    app, manager, tmp_path, monkeypatch
):
    from ui.main_menu import MainMenuWindow

    monkeypatch.setattr(npw, "CONFIRM_DISCARD", False)
    with patch("ui.main_menu.RECENT_PROGRAMS_FILE", tmp_path / "recent_programs.json"):
        menu = MainMenuWindow(manager)
        menu.new_button.click()
        editor = menu.new_program_window
        assert isinstance(editor, NewProgramWindow) and editor.isVisible()

        editor.name_edit.setText("From scratch")
        save_to(editor, tmp_path / "from_scratch.json")

        assert menu.program_panel.opened.path == tmp_path / "from_scratch.json"
        assert menu.program_panel.opened.program.name == "From scratch"
        assert "From scratch" in menu.recent_list.item(0).text()

        # ...and it can now be edited on the menu, saving to the same file.
        menu.program_panel.table.item(0, 2).setData(Qt.UserRole, 2.0)
        assert manager.load(tmp_path / "from_scratch.json").channels[0].amplitude_ma == 2.0
        menu.close()
