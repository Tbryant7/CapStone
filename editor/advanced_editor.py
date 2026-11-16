"""Advanced program panel: independent channel values at each time step.

Uses the existing Program model, ValidationEngine and ProgramFileManager.
Edits stay in memory; saving always asks for a destination.
"""

from __future__ import annotations

import copy
import math
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView, QFileDialog, QFormLayout, QGroupBox, QHBoxLayout, QHeaderView,
    QLabel, QLineEdit, QMessageBox, QPushButton, QDoubleSpinBox,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget, QStackedWidget,
)

from files import Channel, Program, ProgramFileError, TimeSeriesPoint
from files.program_file_manager import OpenedProgram
from files.stim_matrix import export_mat

MAX_CHANNELS = 32
MAX_CELLS = 100_000
PROGRAMS_FOLDER = Path(__file__).resolve().parent.parent / "programs"


class _TimeStepBox(QDoubleSpinBox):
    """Show whole milliseconds without unnecessary trailing zeros."""

    def textFromValue(self, value: float) -> str:
        return f"{value:.6f}".rstrip("0").rstrip(".")


class AdvancedEditor(QGroupBox):
    """A table editor for the same time-series programs MATLAB imports use."""

    changed = Signal()
    program_saved = Signal(object)

    def __init__(self, file_manager, parent=None) -> None:
        super().__init__("Advanced Program", parent)
        self.file_manager = file_manager
        self.dirty = False
        self._loading = False
        self.path = None
        self._constant_program = False
        self.has_program = False
        self._build()
        self.clear()

    def _build(self) -> None:
        outer = QVBoxLayout(self)
        self._pages = QStackedWidget()
        outer.addWidget(self._pages)
        empty_page = QWidget()
        empty_layout = QVBoxLayout(empty_page)
        empty_layout.addStretch()
        self.empty_label = QLabel(
            "No program open. Use New Program, Open Selected or Import Program to begin."
        )
        self.empty_label.setWordWrap(True)
        empty_layout.addWidget(self.empty_label)
        empty_layout.addStretch()
        self._pages.addWidget(empty_page)
        edit_page = QWidget()
        self._pages.addWidget(edit_page)
        editor_layout = QVBoxLayout(edit_page)
        editor_layout.setContentsMargins(0, 0, 0, 0)
        settings = QHBoxLayout()
        details_column = QVBoxLayout()
        details = QFormLayout()
        details.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        details.setFormAlignment(Qt.AlignLeft | Qt.AlignTop)
        details.setLabelAlignment(Qt.AlignLeft)
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("Program name")
        self.description_edit = QLineEdit()
        self.description_edit.setPlaceholderText("Optional")
        self.time_step_box = _TimeStepBox()
        self.time_step_box.setDecimals(6)
        self.time_step_box.setRange(0.000001, 100000)
        details.addRow("Program name:", self.name_edit)
        details.addRow("Description:", self.description_edit)
        details.addRow("Time step (ms):", self.time_step_box)
        details_column.addLayout(details)
        self.summary_label = QLabel()
        self.summary_label.setWordWrap(True)
        details_column.addWidget(self.summary_label)
        settings.addLayout(details_column, 1)

        self.channel_table = QTableWidget(0, 2)
        self.channel_table.setObjectName("channelTable")
        self.channel_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.channel_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.channel_table.setHorizontalHeaderLabels(["WSS channel", "Frequency (Hz)"])
        self.channel_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.channel_table.setFixedHeight(125)
        settings.addWidget(self.channel_table, 1)
        editor_layout.addLayout(settings)
        instruction = QLabel(
            "Set pulse width and amplitude independently for each channel at every time step."
        )
        instruction.setWordWrap(True)
        editor_layout.addWidget(instruction)

        toolbar = QHBoxLayout()
        for text, slot in (
            ("Add Channel", self.add_channel),
            ("Remove Channel", self.remove_channel),
            ("Add Time Step", self.add_step),
            ("Duplicate Time Step", self.duplicate_step),
            ("Remove Time Step", self.remove_step),
        ):
            button = QPushButton(text)
            button.clicked.connect(slot)
            if text == "Remove Channel":
                self.remove_channel_button = button
                button.setEnabled(False)
                button.setStyleSheet(
                    "QPushButton:disabled { background-color: #eeeeee; border-color: #bdbdbd; color: #9e9e9e; }"
                )
            toolbar.addWidget(button)
        editor_layout.addLayout(toolbar)
        self.table = QTableWidget()
        self.table.setObjectName("channelTable")
        self.table.setAlternatingRowColors(True)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setMinimumHeight(84)
        editor_layout.addWidget(self.table, 1)

        self.validation_label = QLabel()
        self.problems_label = QLabel()
        self.problems_label.setWordWrap(True)
        self.problems_label.setStyleSheet("color: #b00020;")
        # Only the tables scroll; validation and save actions remain visible.
        editor_layout.addWidget(self.validation_label)
        editor_layout.addWidget(self.problems_label)
        buttons = QHBoxLayout()
        self.save_status = QLabel("Unsaved program")
        buttons.addWidget(self.save_status, 1)
        self.save_button = QPushButton("Save Program...")
        self.copy_button = QPushButton("Save a copy...")
        self.export_button = QPushButton("Export .mat...")
        self.save_button.clicked.connect(self.save)
        self.copy_button.clicked.connect(self.save)
        self.export_button.clicked.connect(self.export_mat)
        for button in (self.save_button, self.copy_button, self.export_button):
            button.setStyleSheet(
                "QPushButton:disabled { background-color: #eeeeee; border-color: #bdbdbd; color: #9e9e9e; }"
            )
            buttons.addWidget(button)
        editor_layout.addLayout(buttons)
        self.name_edit.textChanged.connect(self._edited)
        self.description_edit.textChanged.connect(self._edited)
        self.time_step_box.valueChanged.connect(self._edited)
        self.channel_table.itemChanged.connect(self._edited)
        self.channel_table.itemSelectionChanged.connect(self._update_channel_selection)
        self.table.itemChanged.connect(self._edited)

    @staticmethod
    def _number(table, row, col):
        item = table.item(row, col)
        text = item.text().strip() if item else ""
        if not text:
            return None
        try:
            value = float(text)
            return value if math.isfinite(value) else text
        except ValueError:
            return text

    @staticmethod
    def _put(table, row, col, value) -> None:
        text = "" if value is None else f"{value:g}" if isinstance(value, (int, float)) else str(value)
        table.setItem(row, col, QTableWidgetItem(text))

    def program(self) -> Program:
        channels = []
        step_s = self.time_step_box.value() / 1000
        for col in range(self.channel_table.rowCount()):
            points = [TimeSeriesPoint(
                time_s=round(row * step_s, 12),
                pulse_width_us=self._number(self.table, row, col * 2 + 1),
                amplitude_ma=self._number(self.table, row, col * 2 + 2),
            ) for row in range(self.table.rowCount())]
            channels.append(Channel(
                number=self._number(self.channel_table, col, 0),
                frequency_hz=self._number(self.channel_table, col, 1),
                pulse_width_us=points[0].pulse_width_us if points else None,
                amplitude_ma=points[0].amplitude_ma if points else None,
                time_series=[] if self._constant_program and len(points) == 1 else points,
            ))
        return Program(self.name_edit.text().strip(), self.description_edit.text().strip(),
                       self.time_step_box.value(), channels)

    def snapshot(self):
        """Return an independently validated copy for the existing runner."""
        if not self.has_program:
            return None
        program = self.program()
        if not program.name or not program.channels or not self.table.rowCount():
            return None
        result = self.file_manager.engine.validate(program)
        if not result.is_valid:
            return None
        return OpenedProgram(copy.deepcopy(program), result,
                             self.path or PROGRAMS_FOLDER / "untitled.json")

    def confirm_discard(self) -> bool:
        if not self.dirty:
            return True
        return QMessageBox.question(
            self, "Unsaved Advanced changes",
            "Discard the unsaved Advanced changes?",
            QMessageBox.Discard | QMessageBox.Cancel, QMessageBox.Cancel,
        ) == QMessageBox.Discard

    def clear(self) -> None:
        """Match the Main Menu's initial state without creating a draft."""
        self._loading = True
        self.has_program = False
        self.path = None
        self.name_edit.clear()
        self.description_edit.clear()
        self.channel_table.setRowCount(0)
        self.table.setRowCount(0)
        self.table.setColumnCount(1)
        self._loading = False
        self.dirty = False
        self._pages.setCurrentIndex(0)
        self._refresh()

    def new_program(self) -> None:
        self.has_program = True
        self._pages.setCurrentIndex(1)
        self._loading = True
        self.path = None
        self._constant_program = False
        self.name_edit.clear()
        self.description_edit.clear()
        self.time_step_box.setValue(100)
        self.channel_table.setRowCount(0)
        self.table.clear()
        self.table.setRowCount(1)
        self.table.setColumnCount(1)
        self.add_channel(number=1)
        self._loading = False
        self.dirty = False
        self._refresh()

    def load_program(self, opened) -> bool:
        """Load without altering the source file or approximating imported points."""
        program = opened.program
        series = [ch.time_series for ch in program.channels if ch.time_series]
        rows = len(series[0]) if series else 1
        step = program.time_step_ms
        if (not isinstance(step, (int, float)) or not math.isfinite(step)
                or not 0.000001 <= step <= 100000
                or not math.isclose(step, round(step, 6), rel_tol=0, abs_tol=1e-10)
                or rows * max(1, len(program.channels) * 2) > MAX_CELLS
                or len(program.channels) > MAX_CHANNELS):
            QMessageBox.warning(self, "Cannot edit in Advanced", "This program is too large or has an unsupported time step.")
            return False
        # Frequency-over-time imports are supported by the runner, but this
        # editor exposes one frequency per channel. Never flatten those files.
        if any(p.frequency_hz is not None and p.frequency_hz != ch.frequency_hz
               for ch in program.channels for p in ch.time_series):
            QMessageBox.warning(self, "Cannot edit in Advanced",
                                "This program changes frequency over time. Use the existing import/execution workflow; Advanced editing has not changed it.")
            return False
        for points in series:
            if len(points) != rows or any(
                not isinstance(p.time_s, (int, float)) or not math.isfinite(p.time_s)
                or not math.isclose(p.time_s, i * step / 1000, abs_tol=1e-9)
                for i, p in enumerate(points)
            ):
                QMessageBox.warning(self, "Cannot edit in Advanced",
                                    "Advanced editing requires matching channel timelines starting at 0 s. The program was not changed.")
                return False
        self.has_program = True
        self._pages.setCurrentIndex(1)
        self._loading = True
        self.path = Path(opened.path)
        self._constant_program = not series
        self.name_edit.setText(program.name)
        self.description_edit.setText(program.description)
        self.time_step_box.setValue(step)
        self.channel_table.setRowCount(0)
        self.table.clear()
        self.table.setRowCount(rows)
        self.table.setColumnCount(1)
        for index, ch in enumerate(program.channels):
            self.add_channel(number=ch.number)
            self._put(self.channel_table, index, 1, ch.frequency_hz)
            for row in range(rows):
                point = ch.time_series[row] if ch.time_series else ch
                self._put(self.table, row, index * 2 + 1, point.pulse_width_us)
                self._put(self.table, row, index * 2 + 2, point.amplitude_ma)
        self._loading = False
        self.dirty = False
        self._refresh()
        return True

    def add_channel(self, checked=False, *, number=None) -> None:
        count = self.channel_table.rowCount()
        if count >= MAX_CHANNELS or self.table.rowCount() * (count + 1) * 2 > MAX_CELLS:
            return
        loading = self._loading
        self._loading = True
        used = [self._number(self.channel_table, row, 0) for row in range(count)]
        if number is None:
            number = next(n for n in range(1, MAX_CHANNELS + 2) if n not in used)
        self.channel_table.setRowCount(count + 1)
        self._put(self.channel_table, count, 0, number)
        self.table.setColumnCount(1 + (count + 1) * 2)
        self._loading = loading
        self._edited()

    def _selected_channel_row(self) -> int:
        rows = self.channel_table.selectionModel().selectedRows()
        return rows[0].row() if rows else -1

    def _update_channel_selection(self) -> None:
        row = self._selected_channel_row()
        selected = self.has_program and row >= 0
        self.remove_channel_button.setEnabled(selected)
        item = self.channel_table.item(row, 0) if selected else None
        number = item.text().strip() if item else ""
        self.remove_channel_button.setText(
            f"Remove Channel {number}" if number else "Remove Channel"
        )

    def remove_channel(self) -> None:
        row = self._selected_channel_row()
        if row < 0:
            return
        item = self.channel_table.item(row, 0)
        number = item.text().strip() if item else "selected"
        if QMessageBox.question(self, "Remove channel", f"Remove channel {number} and its values?",
                                QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
            return
        self._loading = True
        self.channel_table.removeRow(row)
        self.table.removeColumn(row * 2 + 2)
        self.table.removeColumn(row * 2 + 1)
        self.channel_table.clearSelection()
        self.channel_table.setCurrentCell(-1, -1)
        self._loading = False
        self._edited()

    def add_step(self) -> None:
        if (self.table.rowCount() + 1) * max(2, self.channel_table.rowCount() * 2) > MAX_CELLS:
            return
        self._constant_program = False
        self.table.insertRow(self.table.rowCount())
        self._edited()

    def duplicate_step(self) -> None:
        source = self.table.currentRow()
        if source < 0:
            return
        if (self.table.rowCount() + 1) * max(2, self.channel_table.rowCount() * 2) > MAX_CELLS:
            return
        self._loading = True
        self._constant_program = False
        self.table.insertRow(source + 1)
        for col in range(1, self.table.columnCount()):
            item = self.table.item(source, col)
            if item is not None:
                self.table.setItem(source + 1, col, item.clone())
        self._loading = False
        self._edited()

    def remove_step(self) -> None:
        row = self.table.currentRow()
        if row < 0 or self.table.rowCount() <= 1:
            return
        if QMessageBox.question(self, "Remove time step", "Remove this time step and shift later values earlier?",
                                QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
            return
        self.table.removeRow(row)
        self._edited()

    def _edited(self, *args) -> None:
        if not self._loading:
            self.dirty = True
            self._refresh()

    def _refresh(self) -> None:
        if not self.has_program:
            for button in (self.save_button, self.copy_button, self.export_button):
                button.setEnabled(False)
            self._update_channel_selection()
            self.validation_label.clear()
            self.problems_label.clear()
            self.changed.emit()
            return
        self._loading = True
        headers = ["Time (ms)"]
        for row in range(self.channel_table.rowCount()):
            number = self._number(self.channel_table, row, 0)
            label = f"{number:g}" if isinstance(number, (int, float)) else str(number or "?")
            headers += [f"Channel {label}\nPulse width (µs)", f"Channel {label}\nAmplitude (mA)"]
        self.table.setHorizontalHeaderLabels(headers)
        for row in range(self.table.rowCount()):
            self._put(self.table, row, 0, round(row * self.time_step_box.value(), 9))
            self.table.item(row, 0).setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
        rows, channels = self.table.rowCount(), self.channel_table.rowCount()
        duration = max(0, rows - 1) * self.time_step_box.value() / 1000
        self.summary_label.setText(f"Total time: {duration:g} s · Active channels: {channels} · {rows} time steps")
        program = self.program()
        result = self.file_manager.engine.validate(program)
        problems = ([] if program.name else ["Give the program a name."]) + result.failed_parameters
        if not rows:
            problems.insert(0, "Add at least one time step.")
        incomplete = not program.name or any(
            ch.frequency_hz is None or any(p.pulse_width_us is None or p.amplitude_ma is None
                                          for p in ch.time_series)
            for ch in program.channels
        )
        state = "Incomplete" if incomplete else "Failed" if problems else "Passed"
        self.validation_label.setText(f"Validation: {state}")
        color = "#616161" if incomplete else "#b00020" if problems else "#2d6a1f"
        self.validation_label.setStyleSheet(f"color: {color}; font-weight: bold;")
        if incomplete:
            self.problems_label.setText("Complete the program name and channel values to validate.")
            self.problems_label.setStyleSheet("color: #616161;")
        else:
            self.problems_label.setText("\n".join(problems[:2]) +
                                        ("\nMore values need attention." if len(problems) > 2 else ""))
            self.problems_label.setStyleSheet("color: #b00020;")
        self.problems_label.setToolTip("\n".join(problems))
        for button in (self.save_button, self.copy_button, self.export_button):
            button.setEnabled(not problems)
        self.save_status.setText((self.path.name if self.path else "New program") +
                                 (" · unsaved changes" if self.dirty else ""))
        self._loading = False
        self._update_channel_selection()
        self.changed.emit()

    def save(self) -> bool:
        if self.snapshot() is None:
            return False
        suggested = PROGRAMS_FOLDER / "advanced_program.json"
        path, _ = QFileDialog.getSaveFileName(self, "Save Advanced program", str(suggested), "JSON Files (*.json)")
        if not path:
            return False
        target = Path(path).with_suffix(".json")
        samples = Path(__file__).resolve().parent.parent / "samples"
        if target.resolve().is_relative_to(samples.resolve()):
            QMessageBox.warning(self, "Not saved", "Save your program outside the samples folder.")
            return False
        # Confirm the final path too: adding .json may select a different file.
        if target.exists() and QMessageBox.question(
            self, "Replace file", f"Replace {target.name}?", QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        ) != QMessageBox.Yes:
            return False
        try:
            self.file_manager.save(self.program(), target)
        except ProgramFileError as ex:
            QMessageBox.warning(self, "Not saved", str(ex))
            return False
        self.path = target
        self.dirty = False
        self._refresh()
        self.program_saved.emit(self.file_manager.open(target))
        return True

    def export_mat(self) -> None:
        snapshot = self.snapshot()
        if snapshot is None:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Export MATLAB file", str(PROGRAMS_FOLDER / "advanced_program.mat"), "MATLAB Files (*.mat)")
        if not path:
            return
        target = Path(path).with_suffix(".mat")
        samples = Path(__file__).resolve().parent.parent / "samples"
        if target.resolve().is_relative_to(samples.resolve()):
            QMessageBox.warning(self, "Not exported", "Export your program outside the samples folder.")
            return
        if target.exists() and QMessageBox.question(
            self, "Replace file", f"Replace {target.name}?", QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        ) != QMessageBox.Yes:
            return
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            export_mat(snapshot.program, target)
        except (OSError, ValueError) as ex:
            QMessageBox.warning(self, "Not exported", str(ex))
