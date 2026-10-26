"""Read-only "Opened Program" panel for the Main Menu (Sprint 2).

Shows the program that was opened: its name, each channel's pulse width,
amplitude and frequency, and the ValidationEngine result ("Passed" or the
list of failed values). Nothing here can be edited. It is a placeholder until
the Beginner Editor arrives in Sprint 3.

    panel = ProgramPanel(ranges)
    panel.show_program(file_manager.open(path))
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor, QFont
from PySide6.QtWidgets import (
    QAbstractItemView,
    QGroupBox,
    QHeaderView,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from files import OpenedProgram

#: Table columns: (header, Channel attribute, RangeTable parameter).
COLUMNS = (
    ("Channel", "number", None),
    ("Pulse width (µs)", "pulse_width_us", "pulse_width"),
    ("Amplitude (mA)", "amplitude_ma", "amplitude"),
    ("Frequency (Hz)", "frequency_hz", "frequency"),
)

EMPTY_TEXT = "No program open. Use Import Program to open a program file (try the samples folder)."

PASSED_STYLE = "color: #2d6a1f; font-weight: bold;"
FAILED_STYLE = "color: #b00020; font-weight: bold;"
OUT_OF_RANGE_BACKGROUND = QColor("#fde2e4")
OUT_OF_RANGE_TEXT = QColor("#b00020")


class ProgramPanel(QGroupBox):
    def __init__(self, ranges=None, parent=None) -> None:
        super().__init__("Opened Program", parent)
        self.setObjectName("programPanel")
        self.ranges = ranges
        self.opened: OpenedProgram | None = None

        layout = QVBoxLayout(self)

        self.name_label = QLabel(EMPTY_TEXT)
        self.name_label.setObjectName("programName")
        self.name_label.setWordWrap(True)
        self.name_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(self.name_label)

        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setObjectName("channelTable")
        self.table.setHorizontalHeaderLabels([header for header, _, _ in COLUMNS])
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionMode(QAbstractItemView.NoSelection)
        self.table.setFocusPolicy(Qt.NoFocus)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        layout.addWidget(self.table, 1)

        self.validation_label = QLabel()
        self.validation_label.setObjectName("validationResult")
        layout.addWidget(self.validation_label)

        self.problems_label = QLabel()
        self.problems_label.setObjectName("validationProblems")
        self.problems_label.setWordWrap(True)
        self.problems_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.problems_label.setStyleSheet("color: #b00020;")
        layout.addWidget(self.problems_label)

        self.clear()

    # ------------------------------------------------------------ public

    def clear(self) -> None:
        self.opened = None
        self.name_label.setText(EMPTY_TEXT)
        self.table.setRowCount(0)
        self.table.hide()
        self.validation_label.clear()
        self.validation_label.hide()
        self.problems_label.clear()
        self.problems_label.hide()

    def show_program(self, opened: OpenedProgram) -> None:
        self.opened = opened
        program, result = opened.program, opened.validation

        self.name_label.setText(f"<b>{_escape(program.name)}</b> &nbsp; ({_escape(opened.path.name)})")

        self.table.setRowCount(len(program.channels))
        for row, channel in enumerate(program.channels):
            for column, (_, attribute, parameter) in enumerate(COLUMNS):
                value = getattr(channel, attribute)
                item = QTableWidgetItem(_format(value))
                item.setTextAlignment(Qt.AlignCenter)
                if parameter and not self._in_range(parameter, value):
                    # The words are in the problems list below; red is an extra cue.
                    item.setText(f"{_format(value)}  ✖ out of range")
                    item.setBackground(QBrush(OUT_OF_RANGE_BACKGROUND))
                    item.setForeground(QBrush(OUT_OF_RANGE_TEXT))
                    bold = QFont(item.font())
                    bold.setBold(True)
                    item.setFont(bold)
                self.table.setItem(row, column, item)
        self.table.show()

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

    # ------------------------------------------------------------ helpers

    def _in_range(self, parameter: str, value) -> bool:
        if self.ranges is None:
            return True
        try:
            return self.ranges[parameter].contains(value)
        except (KeyError, TypeError):
            return True


def _format(value) -> str:
    return f"{value:g}" if isinstance(value, (int, float)) and not isinstance(value, bool) else str(value)


def _escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
