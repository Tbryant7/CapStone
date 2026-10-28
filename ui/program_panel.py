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

        self.clear()

    # ------------------------------------------------------------ public

    def clear(self) -> None:
        self.opened = None
        self.name_label.setText(EMPTY_TEXT)
        self.table.setRowCount(0)
        self.table.hide()
        self.time_series_label.clear()
        self.time_series_label.hide()
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
                values = _cell_values(channel, attribute)
                text = _format_span(values)
                item = QTableWidgetItem(text)
                item.setTextAlignment(Qt.AlignCenter)
                if parameter and not all(self._in_range(parameter, v) for v in values):
                    # The words are in the problems list below; red is an extra cue.
                    item.setText(f"{text}  ✖ out of range")
                    item.setBackground(QBrush(OUT_OF_RANGE_BACKGROUND))
                    item.setForeground(QBrush(OUT_OF_RANGE_TEXT))
                    bold = QFont(item.font())
                    bold.setBold(True)
                    item.setFont(bold)
                self.table.setItem(row, column, item)
        self.table.show()

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

    # ------------------------------------------------------------ helpers

    def _in_range(self, parameter: str, value) -> bool:
        if self.ranges is None:
            return True
        try:
            return self.ranges[parameter].contains(value)
        except (KeyError, TypeError):
            return True


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
