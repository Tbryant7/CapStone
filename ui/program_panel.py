"""The "Opened Program" panel on the Main Menu.

Shows the program that was opened: its name, time step, each channel's pulse
width, amplitude and frequency, and the ValidationEngine result ("Passed" or
the list of failed values).

With a ProgramFileManager the values can be edited in place: click a value,
change it, press Enter. Every change is validated straight away, and the
file is saved as soon as every value passes. A change that fails validation
is never written (REQ-17): the file keeps its last safe values until the
problem is fixed. Programs imported from MATLAB / CSV can't be written back,
so they are saved with "Save as JSON...". Files in samples/ are reference
files: edits to them stay in the app until "Save a copy...".

    panel = ProgramPanel(ranges, file_manager)
    panel.show_program(file_manager.open(path))
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDoubleSpinBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QStyledItemDelegate,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from files import OpenedProgram, ProgramFileError

#: Table columns: (header, Channel attribute, RangeTable parameter, decimals).
COLUMNS = (
    ("Channel", "number", None, 0),
    ("Pulse width (µs)", "pulse_width_us", "pulse_width", 0),
    ("Amplitude (mA)", "amplitude_ma", "amplitude", 2),
    ("Frequency (Hz)", "frequency_hz", "frequency", 1),
)

#: Spin boxes allow far more than the safe ranges, so an unsafe value that
#: is already in a file is shown as it is (not silently clipped). The
#: ValidationEngine decides what is safe.
EDIT_MAX = 100000

#: Item data role holding the real number behind a cell's text.
VALUE_ROLE = Qt.UserRole

ROOT = Path(__file__).resolve().parent.parent

#: Reference files: edits are never written back here (use Save a copy).
SAMPLES_FOLDER = ROOT / "samples"

#: Where "Save a copy" / "Save as JSON" suggest saving (not in Git).
PROGRAMS_FOLDER = ROOT / "programs"

EMPTY_TEXT = "No program open. Use Import Program to open a program file (try the samples folder)."
EDIT_HINT = "Click a value to change it, then press Enter. Saved values must pass validation."

PASSED_STYLE = "color: #2d6a1f; font-weight: bold;"
FAILED_STYLE = "color: #b00020; font-weight: bold;"
SAVED_STYLE = "color: #2d6a1f;"
NOT_SAVED_STYLE = "color: #b00020; font-weight: bold;"
OUT_OF_RANGE_BACKGROUND = QColor("#fde2e4")
OUT_OF_RANGE_TEXT = QColor("#b00020")


class ProgramPanel(QGroupBox):
    #: The program's values changed (an OpenedProgram with the new validation).
    program_edited = Signal(object)
    #: The program was written to this path for the first time (Save as JSON).
    program_saved_as = Signal(object)

    def __init__(self, ranges=None, file_manager=None, parent=None) -> None:
        super().__init__("Opened Program", parent)
        self.setObjectName("programPanel")
        self.ranges = ranges
        self.file_manager = file_manager
        self.editable = file_manager is not None
        self.opened: OpenedProgram | None = None
        self._rendering = False

        layout = QVBoxLayout(self)

        self.name_label = QLabel(EMPTY_TEXT)
        self.name_label.setObjectName("programName")
        self.name_label.setWordWrap(True)
        self.name_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(self.name_label)

        step_row = QHBoxLayout()
        self.time_step_label = QLabel("Time step (ms):")
        step_row.addWidget(self.time_step_label)
        self.time_step_box = _spin_box(decimals=0)
        self.time_step_box.setObjectName("timeStepBox")
        self.time_step_box.valueChanged.connect(self._time_step_edited)
        step_row.addWidget(self.time_step_box)
        self.edit_hint = QLabel(EDIT_HINT if self.editable else "")
        self.edit_hint.setObjectName("editHint")
        step_row.addWidget(self.edit_hint, 1)
        layout.addLayout(step_row)

        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setObjectName("channelTable")
        self.table.setHorizontalHeaderLabels([column[0] for column in COLUMNS])
        if self.editable:
            self.table.setItemDelegate(_ValueDelegate(self.table))
            self.table.setEditTriggers(
                QAbstractItemView.CurrentChanged
                | QAbstractItemView.SelectedClicked
                | QAbstractItemView.DoubleClicked
                | QAbstractItemView.EditKeyPressed
                | QAbstractItemView.AnyKeyPressed
            )
            self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        else:
            self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
            self.table.setSelectionMode(QAbstractItemView.NoSelection)
            self.table.setFocusPolicy(Qt.NoFocus)
        self.table.setAlternatingRowColors(True)
        self.table.setMinimumHeight(190)  # header + 4 channels without scrolling
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.itemChanged.connect(self._cell_edited)
        layout.addWidget(self.table, 1)

        #: One line about time-series data (imported from MATLAB / CSV).
        self.time_series_label = QLabel()
        self.time_series_label.setObjectName("timeSeriesSummary")
        self.time_series_label.setWordWrap(True)
        layout.addWidget(self.time_series_label)

        self.validation_label = QLabel()
        self.validation_label.setObjectName("validationResult")
        layout.addWidget(self.validation_label)

        self.problems_label = QLabel()
        self.problems_label.setObjectName("validationProblems")
        self.problems_label.setWordWrap(True)
        self.problems_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.problems_label.setStyleSheet("color: #b00020;")
        layout.addWidget(self.problems_label)

        save_row = QHBoxLayout()
        self.save_status_label = QLabel()
        self.save_status_label.setObjectName("saveStatus")
        self.save_status_label.setWordWrap(True)
        save_row.addWidget(self.save_status_label, 1)
        self.save_as_button = QPushButton("Save as JSON...")
        self.save_as_button.setObjectName("saveAsButton")
        self.save_as_button.clicked.connect(self.save_as)
        save_row.addWidget(self.save_as_button)
        layout.addLayout(save_row)

        self.clear()

    # ------------------------------------------------------------ public

    def clear(self) -> None:
        self.opened = None
        self.name_label.setText(EMPTY_TEXT)
        self.table.setRowCount(0)
        for widget in (
            self.table, self.time_step_label, self.time_step_box, self.edit_hint,
            self.time_series_label, self.validation_label, self.problems_label,
            self.save_status_label, self.save_as_button,
        ):
            widget.hide()
        self.time_series_label.clear()
        self.validation_label.clear()
        self.problems_label.clear()
        self.save_status_label.clear()

    def show_program(self, opened: OpenedProgram) -> None:
        self.opened = opened
        self.table.setRowCount(0)  # fresh items for a new program
        self._render()
        for widget in (self.table, self.time_step_label, self.time_step_box):
            widget.show()
        self.edit_hint.setVisible(self.editable)
        self.save_as_button.setVisible(self.editable)
        # An import can only be kept as JSON; a JSON file can be copied to
        # build a new program off it without changing the original.
        self.save_as_button.setText(self._save_as_text())
        reason = self._read_only_reason()
        if self.editable and reason:
            self._set_save_status(
                f"Changes stay in the app ({reason}). Use {self._save_as_text()} to keep them.",
                ok=True,
            )
        else:
            self.save_status_label.clear()
            self.save_status_label.hide()

    def save_as(self) -> bool:
        """Ask for a .json path and save the program there. Returns True if saved."""
        if self.opened is None or self.file_manager is None:
            return False
        suggested = self.opened.path.with_suffix(".json")
        if self._read_only_reason():
            PROGRAMS_FOLDER.mkdir(parents=True, exist_ok=True)
            suggested = PROGRAMS_FOLDER / suggested.name
        path, _ = QFileDialog.getSaveFileName(
            self, "Save program as JSON", str(suggested), "JSON Files (*.json)"
        )
        if not path:
            return False
        path = Path(path)
        if path.suffix.lower() != ".json":
            path = path.with_suffix(".json")
        try:
            self.file_manager.save(self.opened.program, path)
        except ProgramFileError as ex:
            QMessageBox.warning(self, "Not saved", str(ex))
            return False
        self.opened = OpenedProgram(self.opened.program, self.opened.validation, path)
        self._render()
        self._set_save_status(f"Saved to {path.name} at {_now()}.", ok=True)
        self.program_saved_as.emit(self.opened)
        return True

    # ------------------------------------------------------------ editing

    def _cell_edited(self, item: QTableWidgetItem) -> None:
        if self._rendering or self.opened is None:
            return
        _, attribute, _, decimals = COLUMNS[item.column()]
        channel = self.opened.program.channels[item.row()]
        value = _number(item.data(VALUE_ROLE), decimals)
        if getattr(channel, attribute) == value:
            return
        setattr(channel, attribute, value)
        self._program_changed()

    def _time_step_edited(self, value: float) -> None:
        if self._rendering or self.opened is None:
            return
        program = self.opened.program
        value = _number(value, 0)
        if program.time_step_ms == value:
            return
        program.time_step_ms = value
        self._program_changed()

    def _program_changed(self) -> None:
        """Re-validate, redraw, and save the file if every value passes."""
        program, path = self.opened.program, self.opened.path
        result = self.file_manager.engine.validate(program)
        self.opened = OpenedProgram(program, result, path)
        self._render()

        reason = self._read_only_reason()
        if reason:
            self._set_save_status(
                f"Changed, not saved: {reason}. Use {self._save_as_text()} to keep it.",
                ok=False,
            )
        elif not result.is_valid:
            self._set_save_status(
                f"Not saved: fix the values in red first. {path.name} still has "
                "its last safe values.", ok=False,
            )
        else:
            try:
                self.file_manager.save(program, path)
            except ProgramFileError as ex:
                self._set_save_status(f"Not saved: {ex}", ok=False)
            else:
                self._set_save_status(f"Saved to {path.name} at {_now()}.", ok=True)
        self.program_edited.emit(self.opened)

    def _read_only_reason(self) -> str:
        """Why edits aren't written to the opened file, or "" if they are."""
        if self.opened is None:
            return ""
        path = self.opened.path
        if path.suffix.lower() != ".json":
            return f"{path.name} is an import"
        if _inside(path, SAMPLES_FOLDER):
            return f"{path.name} is a sample, and samples are kept as they are"
        return ""

    def _writes_back(self) -> bool:
        return self.opened is not None and not self._read_only_reason()

    def _save_as_text(self) -> str:
        imported = self.opened is not None and self.opened.path.suffix.lower() != ".json"
        return "Save as JSON..." if imported else "Save a copy..."

    def _set_save_status(self, text: str, ok: bool) -> None:
        self.save_status_label.setText(text)
        self.save_status_label.setStyleSheet(SAVED_STYLE if ok else NOT_SAVED_STYLE)
        self.save_status_label.show()

    # ------------------------------------------------------------ drawing

    def _render(self) -> None:
        self._rendering = True
        try:
            self._render_values()
        finally:
            self._rendering = False

    def _render_values(self) -> None:
        program, result = self.opened.program, self.opened.validation

        self.name_label.setText(
            f"<b>{_escape(program.name)}</b> &nbsp; ({_escape(self.opened.path.name)})"
        )
        step = program.time_step_ms
        self.time_step_box.setValue(step if _is_number(step) else 0)
        # A time series' points are a fixed time apart, so its step is fixed.
        self.time_step_box.setEnabled(
            self.editable and not any(c.time_series for c in program.channels)
        )

        self.table.setRowCount(len(program.channels))
        for row, channel in enumerate(program.channels):
            for column, (_, attribute, parameter, decimals) in enumerate(COLUMNS):
                item = self.table.item(row, column)
                if item is None:
                    item = QTableWidgetItem()
                    item.setTextAlignment(Qt.AlignCenter)
                    self.table.setItem(row, column, item)
                self._fill_cell(item, channel, attribute, parameter, decimals)

        summary = _time_series_summary(program)
        self.time_series_label.setText(summary)
        self.time_series_label.setVisible(bool(summary))

        if result.is_valid:
            self.validation_label.setText("Validation: Passed")
            self.validation_label.setStyleSheet(PASSED_STYLE)
            self.problems_label.clear()
            self.problems_label.hide()
        else:
            count = len(result.failed_parameters)
            self.validation_label.setText(
                f"Validation: Failed ({count} problem{'s' if count != 1 else ''})"
            )
            self.validation_label.setStyleSheet(FAILED_STYLE)
            self.problems_label.setText("\n".join(f"• {p}" for p in result.failed_parameters))
            self.problems_label.show()
        self.validation_label.show()

    def _fill_cell(self, item, channel, attribute, parameter, decimals) -> None:
        values = _cell_values(channel, attribute)
        text = _format_span(values)
        bad = parameter and not all(self._in_range(parameter, v) for v in values)

        # The channel number and time-series values (which change over
        # time) can't be typed over; everything else can.
        varies = len(values) > 1
        flags = Qt.ItemIsEnabled
        if self.editable and parameter and not varies:
            flags |= Qt.ItemIsSelectable | Qt.ItemIsEditable
            item.setData(VALUE_ROLE, values[0])
            item.setData(_DECIMALS_ROLE, decimals)
        item.setFlags(flags)

        font = QFont(item.font())
        font.setBold(bool(bad))
        item.setFont(font)
        if bad:
            # The words are in the problems list below; red is an extra cue.
            item.setText(f"{text}  ✖ out of range")
            item.setBackground(QBrush(OUT_OF_RANGE_BACKGROUND))
            item.setForeground(QBrush(OUT_OF_RANGE_TEXT))
        else:
            item.setText(text)
            item.setData(Qt.BackgroundRole, None)
            item.setData(Qt.ForegroundRole, None)

    def _in_range(self, parameter: str, value) -> bool:
        if self.ranges is None:
            return True
        try:
            return self.ranges[parameter].contains(value)
        except (KeyError, TypeError):
            return True


#: Item data role holding how many decimals a cell's spin box shows.
_DECIMALS_ROLE = Qt.UserRole + 1


class _ValueDelegate(QStyledItemDelegate):
    """Edits a cell with a spin box over its number (not its display text)."""

    def createEditor(self, parent, option, index):  # noqa: N802 (Qt name)
        return _spin_box(index.data(_DECIMALS_ROLE) or 0, parent)

    def setEditorData(self, editor, index):  # noqa: N802 (Qt name)
        value = index.data(VALUE_ROLE)
        editor.setValue(value if _is_number(value) else 0)
        editor.selectAll()

    def setModelData(self, editor, model, index):  # noqa: N802 (Qt name)
        editor.interpretText()
        model.setData(index, editor.value(), VALUE_ROLE)


def _spin_box(decimals: int, parent=None) -> QDoubleSpinBox:
    box = QDoubleSpinBox(parent)
    box.setDecimals(decimals)
    box.setRange(0, EDIT_MAX)
    box.setSingleStep(1 if decimals == 0 else 0.1)
    box.setKeyboardTracking(False)  # one change per Enter / arrow click, not per keystroke
    box.setAlignment(Qt.AlignCenter)
    return box


def _number(value, decimals: int):
    """Whole numbers stay ``int`` (50, not 50.0) so files stay tidy."""
    value = round(float(value), decimals)
    return int(value) if decimals == 0 else value


def _is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _now() -> str:
    return datetime.now().strftime("%H:%M:%S")


def _cell_values(channel, attribute: str) -> list:
    """The value(s) to show: every point's value for a time-series channel."""
    points = getattr(channel, "time_series", None) or []
    if points and attribute in ("pulse_width_us", "amplitude_ma"):
        return [getattr(p, attribute) for p in points]
    return [getattr(channel, attribute)]


def _format_span(values: list) -> str:
    """One value as is; a time series as "low – high" (or one value if flat)."""
    numbers = [v for v in values if isinstance(v, (int, float)) and not isinstance(v, bool)]
    if len(values) == 1 or len(numbers) != len(values):
        return _format(values[0]) if len(values) == 1 else "varies"
    low, high = min(numbers), max(numbers)
    return _format(low) if low == high else f"{_format(low)} – {_format(high)}"


def _time_series_summary(program) -> str:
    counted = [c for c in program.channels if getattr(c, "time_series", None)]
    if not counted:
        return ""
    points = counted[0].time_series
    times = [p.time_s for p in points if isinstance(p.time_s, (int, float))]
    span = f", {_format(min(times))} – {_format(max(times))} s" if times else ""
    step = program.time_step_ms
    step_text = f", {_format(step)} ms step" if isinstance(step, (int, float)) else ""
    return (
        f"Time series: {len(points)} points per channel{span}{step_text}. "
        "Pulse width and amplitude show the lowest – highest value over time."
    )


def _format(value) -> str:
    return f"{value:g}" if isinstance(value, (int, float)) and not isinstance(value, bool) else str(value)


def _escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _inside(path: Path, folder: Path) -> bool:
    try:
        Path(path).resolve().relative_to(folder.resolve())
    except (OSError, ValueError):
        return False
    return True
