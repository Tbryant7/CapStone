"""Advanced editing preserves independent time steps and existing workflows."""

from pathlib import Path
from unittest.mock import patch

import pytest
from PySide6.QtWidgets import QApplication, QMessageBox

from channels import ProgramRunner, RunState, build_frames
from comms import FakeCommunicationAdapter
from editor.advanced_editor import AdvancedEditor
from files import Channel, Program, ProgramFileManager, TimeSeriesPoint
from files.program_file_manager import OpenedProgram


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def editor(app):
    widget = AdvancedEditor(ProgramFileManager())
    yield widget
    widget.deleteLater()
    app.processEvents()


def opened(program):
    return OpenedProgram(program, ProgramFileManager().engine.validate(program), Path("input.json"))


def example():
    return Program("Independent steps", "Test", 100, [
        Channel(1, 50, 1, 20, [TimeSeriesPoint(0, 50, 1), TimeSeriesPoint(0.1, 60, 2)]),
        Channel(3, 70, 2, 25, [TimeSeriesPoint(0, 70, 2), TimeSeriesPoint(0.1, 80, 1)]),
    ])


def test_independent_channels_and_steps_reach_runner(editor):
    assert editor.load_program(opened(example()))
    editor._put(editor.table, 1, 2, 1.5)
    snapshot = editor.snapshot()
    frames = build_frames(snapshot.program)
    assert frames[1].commands[0].amplitude_ma == 1.5
    assert frames[1].commands[1].amplitude_ma == 1
    assert example().channels[0].time_series[1].amplitude_ma == 2
    adapter = FakeCommunicationAdapter()
    adapter.connect()
    runner = ProgramRunner(adapter, snapshot.program, snapshot.validation)
    runner.start()
    while runner.step():
        pass
    assert runner.state == RunState.COMPLETE
    assert not adapter.stimulating
    adapter.disconnect()


@pytest.mark.parametrize("value", ["", "abc", "nan", "inf", "999999"])
def test_invalid_step_blocks_save_export_and_execution(editor, value):
    editor.load_program(opened(example()))
    editor._put(editor.table, 1, 2, value)
    assert editor.snapshot() is None
    assert not editor.save_button.isEnabled()
    assert not editor.copy_button.isEnabled()
    assert not editor.export_button.isEnabled()


def test_duplicate_step_keeps_other_channels_and_retimes(editor):
    editor.load_program(opened(example()))
    editor.table.setCurrentCell(0, 1)
    editor.duplicate_step()
    program = editor.program()
    assert [p.time_s for p in program.channels[0].time_series] == [0, 0.1, 0.2]
    assert [p.amplitude_ma for p in program.channels[0].time_series] == [1, 1, 2]
    assert [p.amplitude_ma for p in program.channels[1].time_series] == [2, 2, 1]


def test_constant_import_keeps_hold_until_stop_behavior(editor):
    program = example()
    for channel in program.channels:
        channel.time_series = []
    editor.load_program(opened(program))
    assert editor.program().to_dict() == program.to_dict()


def test_variable_frequency_is_never_silently_flattened(editor):
    editor.load_program(opened(example()))
    before = editor.program().to_dict()
    program = example()
    program.channels[0].time_series[1].frequency_hz = 30
    with patch.object(QMessageBox, "warning"):
        assert not editor.load_program(opened(program))
    assert editor.program().to_dict() == before


def test_mismatched_timeline_leaves_draft_untouched(editor):
    editor.load_program(opened(example()))
    before = editor.program().to_dict()
    program = example()
    program.channels[1].time_series.pop()
    with patch.object(QMessageBox, "warning"):
        assert not editor.load_program(opened(program))
    assert editor.program().to_dict() == before


def test_save_roundtrip_does_not_change_input_file(editor, tmp_path):
    source, target = tmp_path / "input.json", tmp_path / "copy.json"
    editor.file_manager.save(example(), source)
    original = source.read_bytes()
    editor.load_program(editor.file_manager.open(source))
    editor._put(editor.table, 1, 2, 1.5)
    with patch("editor.advanced_editor.QFileDialog.getSaveFileName", return_value=(str(target), "")):
        assert editor.save()
    assert source.read_bytes() == original
    assert editor.file_manager.open(target).program.to_dict() == editor.program().to_dict()
    assert not editor.dirty


def test_export_mat_preserves_all_step_values(editor, tmp_path):
    editor.load_program(opened(example()))
    target = tmp_path / "copy.mat"
    with patch("editor.advanced_editor.QFileDialog.getSaveFileName", return_value=(str(target), "")):
        editor.export_mat()
    imported = editor.file_manager.open(target).program
    assert [[p.amplitude_ma for p in ch.time_series] for ch in imported.channels] == [[1, 2], [2, 1]]


def test_switching_keeps_draft_and_uses_execution_snapshot(app, tmp_path):
    from ui.main_menu import MainMenuWindow
    with patch("ui.main_menu.RECENT_PROGRAMS_FILE", tmp_path / "recent.json"):
        adapter = FakeCommunicationAdapter()
        window = MainMenuWindow(adapter=adapter)
        try:
            window._select_mode("Advanced")
            assert window.advanced_editor.load_program(opened(example()))
            window.advanced_editor._put(window.advanced_editor.table, 1, 2, 1.5)
            window._select_mode("Beginner")
            window._select_mode("Advanced")
            assert window.advanced_editor.program().channels[0].time_series[1].amplitude_ma == 1.5
            window.open_execution_screen()
            assert window.execution_window is not None
            window.advanced_editor._put(window.advanced_editor.table, 1, 2, 2)
            assert window.execution_window.runner.program.channels[0].time_series[1].amplitude_ma == 1.5
        finally:
            window.advanced_editor.dirty = False
            window.close()


def test_cancel_new_program_preserves_draft(app, tmp_path):
    from ui.main_menu import MainMenuWindow
    with patch("ui.main_menu.RECENT_PROGRAMS_FILE", tmp_path / "recent.json"):
        window = MainMenuWindow()
        try:
            window._select_mode("Advanced")
            window.advanced_editor.load_program(opened(example()))
            window.advanced_editor.name_edit.setText("Keep my draft")
            before = window.advanced_editor.program().to_dict()
            with patch.object(QMessageBox, "question", return_value=QMessageBox.Cancel):
                window.open_new_program_screen()
                assert not window.close()
            assert window.advanced_editor.program().to_dict() == before
        finally:
            window.advanced_editor.dirty = False
            window.close()


def test_sample_save_is_refused_without_touching_file(editor):
    sample = Path(__file__).resolve().parents[1] / "samples" / "valid_1_channel.json"
    before = sample.read_bytes()
    editor.load_program(opened(example()))
    with patch("editor.advanced_editor.QFileDialog.getSaveFileName", return_value=(str(sample), "")):
        with patch.object(QMessageBox, "warning"):
            assert not editor.save()
    assert sample.read_bytes() == before


def test_snapshot_is_independent_of_later_edits(editor):
    editor.load_program(opened(example()))
    snapshot = editor.snapshot()
    editor._put(editor.table, 1, 2, 1.5)
    assert snapshot.program.channels[0].time_series[1].amplitude_ma == 2


def test_initial_advanced_mode_has_no_program_or_validation(app, tmp_path):
    from ui.main_menu import MainMenuWindow
    with patch("ui.main_menu.RECENT_PROGRAMS_FILE", tmp_path / "recent.json"):
        window = MainMenuWindow()
        try:
            window._select_mode("Advanced")
            assert not window.advanced_editor.has_program
            assert window.advanced_editor.snapshot() is None
            assert window.advanced_editor.validation_label.text() == ""
            assert "Open or create" in window.run_hint.text()
            assert not window.run_button.isEnabled()
        finally:
            window.close()


def test_new_program_explicitly_opens_advanced_draft(app, tmp_path):
    from ui.main_menu import MainMenuWindow
    with patch("ui.main_menu.RECENT_PROGRAMS_FILE", tmp_path / "recent.json"):
        window = MainMenuWindow()
        try:
            window._select_mode("Advanced")
            window.open_new_program_screen()
            assert window.advanced_editor.has_program
            assert window.advanced_editor.channel_table.rowCount() == 1
            assert window.advanced_editor.table.rowCount() == 1
            assert "Incomplete" in window.advanced_editor.validation_label.text()
            assert not window.run_button.isEnabled()
        finally:
            window.close()


def test_open_selected_populates_advanced_editor(app, tmp_path):
    from ui.main_menu import MainMenuWindow
    path = tmp_path / "independent.json"
    ProgramFileManager().save(example(), path)
    with patch("ui.main_menu.RECENT_PROGRAMS_FILE", tmp_path / "recent.json"):
        window = MainMenuWindow()
        try:
            window._select_mode("Advanced")
            window._save_recent_program("Independent steps", "Test", "Not run yet", str(path))
            window.recent_list.setCurrentRow(0)
            window._open_selected_program()
            assert window.advanced_editor.has_program
            assert window.advanced_editor.program().to_dict() == example().to_dict()
            assert "Passed" in window.advanced_editor.validation_label.text()
        finally:
            window.close()


@pytest.mark.parametrize("width,height", [(900, 820), (980, 900), (1440, 900)])
def test_advanced_save_and_validation_stay_visible(app, tmp_path, width, height):
    from ui.main_menu import MainMenuWindow
    with patch("ui.main_menu.RECENT_PROGRAMS_FILE", tmp_path / "recent.json"):
        window = MainMenuWindow()
        try:
            window.resize(width, height)
            window._select_mode("Advanced")
            window.open_new_program_screen()
            window.show()
            app.processEvents()
            editor = window.advanced_editor
            for widget in (editor.save_button, editor.copy_button, editor.export_button,
                           editor.validation_label, editor.problems_label, editor.table):
                assert widget.isVisible()
                top_left = widget.mapTo(editor, widget.rect().topLeft())
                bottom_right = widget.mapTo(editor, widget.rect().bottomRight())
                assert editor.rect().contains(top_left)
                assert editor.rect().contains(bottom_right)
            assert editor.table.mapTo(editor, editor.table.rect().bottomRight()).y() < editor.validation_label.mapTo(editor, editor.validation_label.rect().topLeft()).y()
            menu = window._menu_widget
            description_bottom = window._description_group.mapTo(menu, window._description_group.rect().bottomRight()).y()
            button_top = window.new_button.mapTo(menu, window.new_button.rect().topLeft()).y()
            assert button_top > description_bottom
        finally:
            window.close()


def test_time_step_display_keeps_fractional_precision(editor):
    editor.new_program()
    editor.time_step_box.setValue(100)
    assert editor.time_step_box.text() == "100"
    editor.time_step_box.setValue(100.123456)
    assert editor.time_step_box.text() == "100.123456"


def test_removal_requires_selected_row_even_after_selection_is_cleared(editor):
    editor.load_program(opened(example()))
    assert not editor.remove_channel_button.isEnabled()
    editor.channel_table.selectRow(1)
    assert editor.remove_channel_button.isEnabled()
    assert editor.remove_channel_button.text() == "Remove Channel 3"
    assert len(editor.channel_table.selectedIndexes()) == 2
    editor.channel_table.clearSelection()
    assert not editor.remove_channel_button.isEnabled()
    before = editor.program().to_dict()
    with patch.object(QMessageBox, "question") as question:
        editor.remove_channel()
        question.assert_not_called()
    assert editor.program().to_dict() == before


def test_remove_selected_channel_keeps_other_channel_values(editor):
    program = example()
    editor.load_program(opened(program))
    editor.channel_table.selectRow(0)
    assert editor.remove_channel_button.text() == "Remove Channel 1"
    with patch.object(QMessageBox, "question", return_value=QMessageBox.Yes) as question:
        editor.remove_channel_button.click()
        assert "channel 1" in question.call_args.args[2]
    remaining = editor.program().channels
    assert len(remaining) == 1
    assert remaining[0].to_dict() == program.channels[1].to_dict()
    assert editor.dirty
    assert not editor.remove_channel_button.isEnabled()


def test_cancel_channel_removal_keeps_values_and_selection(editor):
    editor.load_program(opened(example()))
    editor.channel_table.selectRow(1)
    before = editor.program().to_dict()
    with patch.object(QMessageBox, "question", return_value=QMessageBox.No):
        editor.remove_channel_button.click()
    assert editor.program().to_dict() == before
    assert editor.remove_channel_button.isEnabled()
    assert not editor.dirty


def test_remove_button_tracks_edited_channel_number(editor):
    editor.load_program(opened(example()))
    editor.channel_table.selectRow(1)
    editor._put(editor.channel_table, 1, 0, 4)
    assert editor.remove_channel_button.text() == "Remove Channel 4"


def test_new_program_starts_with_one_blank_channel_and_one_time_step(editor):
    editor.new_program()
    assert editor.channel_table.rowCount() == 1
    assert editor.table.rowCount() == 1
    assert editor.table.columnCount() == 3
    assert editor._number(editor.table, 0, 0) == 0
    assert editor._number(editor.table, 0, 1) is None
    assert editor._number(editor.table, 0, 2) is None
    assert editor.snapshot() is None
    assert not editor.remove_channel_button.isEnabled()
