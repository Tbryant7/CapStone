"""Screen 4: Stimulation Execution / Status (SDS Figure 4.5).

Runs the program opened on the Main Menu on the WSS and shows what is
happening: per-channel indicators, a live output log, and one oversized STOP
STIMULATION control that is always available (REQ-18 - REQ-20). Every state
is written in words; color is only an extra cue (SDS 4.5).

For now this is a separate window opened from the Main Menu; it becomes one
of the four screens once the main window with screen switching exists
(SDS Figure 4.1). Runs are limited to the fake / simulated WSS until the safe
limits are confirmed (see channels/program_runner.py).
"""

from __future__ import annotations

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMainWindow,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from channels import ProgramRunner, RunRefused, RunState
from comms import AdapterStatus, CommunicationAdapter, ConnectionState

from .wss_status_bar import WssStatusBar

STATE_COLORS = {
    RunState.READY: "#455a64",
    RunState.RUNNING: "#2e7d32",
    RunState.COMPLETE: "#1565c0",
    RunState.STOPPED: "#6d4c41",
    RunState.ERROR: "#c62828",
}

COLUMNS = ("Channel", "Status", "Pulse width (µs)", "Amplitude (mA)", "Frequency (Hz)")


class _Bridge(QObject):
    changed = Signal(object)


class ExecutionWindow(QMainWindow):
    def __init__(self, opened, adapter: CommunicationAdapter, parent=None) -> None:
        super().__init__(parent)
        self.opened = opened
        self.adapter = adapter
        self.runner = ProgramRunner(adapter, opened.program, opened.validation)
        self._log_shown = len(adapter.command_log)

        self.setWindowTitle("COSMIIC - Stimulation Execution / Status")
        self.setMinimumSize(760, 620)
        self._build()

        self._timer = QTimer(self)
        self._timer.setInterval(max(1, round(self.runner.step_ms or 100)))
        self._timer.timeout.connect(self._tick)

        self._bridge = _Bridge()
        self._bridge.changed.connect(self._on_adapter_status)
        adapter.add_status_listener(self._bridge.changed.emit)

        self.refresh()

    # ------------------------------------------------------------ layout

    def _build(self) -> None:
        root = QWidget()
        layout = QVBoxLayout(root)
        layout.setContentsMargins(16, 16, 16, 12)
        layout.setSpacing(10)

        program, result = self.opened.program, self.opened.validation
        title = QLabel(f"<b>{_escape(program.name)}</b> &nbsp; ({_escape(self.opened.path.name)})")
        title.setStyleSheet("font-size: 16px;")
        layout.addWidget(title)

        checked = QLabel("Validation: Passed" if result.is_valid
                         else f"Validation: Failed ({len(result.failed_parameters)} problems)")
        checked.setObjectName("validationResult")
        checked.setStyleSheet(
            "color: #2d6a1f; font-weight: bold;" if result.is_valid else "color: #b00020; font-weight: bold;"
        )
        layout.addWidget(checked)

        if self.adapter.mode != "hardware":
            banner = QLabel(f"SIMULATED ({self.adapter.mode} mode): no stimulation reaches a person")
            banner.setStyleSheet(
                "background: #ffe082; color: #1a1a1a; padding: 6px 10px; border-radius: 4px; font-weight: bold;"
            )
            layout.addWidget(banner)

        state_row = QHBoxLayout()
        self.state_label = QLabel()
        self.state_label.setObjectName("runState")
        state_row.addWidget(self.state_label)
        self.detail_label = QLabel()
        self.detail_label.setObjectName("runDetail")
        self.detail_label.setWordWrap(True)
        state_row.addWidget(self.detail_label, 1)
        layout.addLayout(state_row)

        self.progress = QProgressBar()
        self.progress.setRange(0, max(1, len(self.runner.frames)))
        self.progress.setTextVisible(False)
        layout.addWidget(self.progress)
        self.progress_label = QLabel()
        self.progress_label.setObjectName("runProgress")
        layout.addWidget(self.progress_label)

        self.table = QTableWidget(len(self.opened.program.channels), len(COLUMNS))
        self.table.setHorizontalHeaderLabels(COLUMNS)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionMode(QAbstractItemView.NoSelection)
        self.table.setFocusPolicy(Qt.NoFocus)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        rows = len(self.opened.program.channels)
        self.table.setFixedHeight(32 + 30 * min(max(rows, 1), 6))
        layout.addWidget(self.table)

        buttons = QHBoxLayout()
        self.run_button = QPushButton("Run")
        self.run_button.setObjectName("runButton")
        self.run_button.setMinimumHeight(56)
        self.run_button.clicked.connect(self.run)
        buttons.addWidget(self.run_button, 1)
        self.stop_button = QPushButton("STOP STIMULATION")
        self.stop_button.setObjectName("stopButton")
        self.stop_button.setMinimumHeight(56)
        self.stop_button.setToolTip("Stops all stimulation immediately. Always available.")
        self.stop_button.clicked.connect(self.stop)
        buttons.addWidget(self.stop_button, 2)
        layout.addLayout(buttons)

        self.reason_label = QLabel()
        self.reason_label.setObjectName("runBlockedReason")
        self.reason_label.setWordWrap(True)
        self.reason_label.setStyleSheet("color: #6d4c41;")
        layout.addWidget(self.reason_label)

        layout.addWidget(QLabel("Live output log:"))
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        mono = QFont("Consolas")
        mono.setStyleHint(QFont.Monospace)
        self.log_view.setFont(mono)
        self.log_view.setMaximumBlockCount(5000)
        layout.addWidget(self.log_view, 1)

        back = QHBoxLayout()
        back.addStretch(1)
        self.back_button = QPushButton("Back to Main Menu")
        self.back_button.clicked.connect(self.close)
        back.addWidget(self.back_button)
        layout.addLayout(back)

        self.setCentralWidget(root)
        self.wss_status_bar = WssStatusBar(self.adapter, show_connect_button=True)
        self.setStatusBar(self.wss_status_bar)
        self.setStyleSheet(
            """
            #runButton { background: #e3f2e1; border: 2px solid #5a963f; border-radius: 6px;
                         font-size: 16px; font-weight: bold; }
            #runButton:disabled { background: #eeeeee; border-color: #bdbdbd; color: #9e9e9e; }
            #stopButton { background: #c62828; color: white; border-radius: 6px;
                          font-size: 20px; font-weight: bold; }
            #stopButton:pressed { background: #8e0000; }
            """
        )

    # ------------------------------------------------------------ actions

    def run(self) -> None:
        try:
            self.runner.start()
        except RunRefused as ex:
            self.reason_label.setText(str(ex))
            return
        if self.runner.state is RunState.RUNNING:
            self._timer.start()
        self.refresh()

    def stop(self) -> None:
        """STOP STIMULATION: always works, even when nothing is running."""
        self._timer.stop()
        self.runner.stop()
        self.refresh()

    def _tick(self) -> None:
        if not self.runner.step():
            self._timer.stop()
        self.refresh()

    def _on_adapter_status(self, status: AdapterStatus) -> None:
        if status.state is ConnectionState.LOST and self.runner.state is RunState.RUNNING:
            self._timer.stop()
            self.runner.connection_lost(status.detail or "WSS connection lost")
        self.refresh()

    # ------------------------------------------------------------ display

    def refresh(self) -> None:
        runner = self.runner
        state = runner.state
        self.state_label.setText(f"State: {state.value}")
        self.state_label.setStyleSheet(f"color: {STATE_COLORS[state]}; font-weight: bold; font-size: 15px;")
        self.detail_label.setText(runner.detail)

        total = len(runner.frames)
        self.progress.setValue(runner.position)
        if runner.is_time_series:
            frame = runner.current
            at = f"t = {frame.time_s:g} s" if frame else "t = 0 s"
            self.progress_label.setText(
                f"Step {runner.position} of {total}  ·  {at} of {runner.duration_s:g} s  ·  "
                f"{runner.step_ms:g} ms per step"
            )
        else:
            self.progress_label.setText(
                "Constant values: sent once when you press Run, then held until STOP."
            )

        self._fill_channels()
        reason = runner.why_not_runnable()
        self.run_button.setEnabled(not reason)
        if state is RunState.RUNNING:
            self.reason_label.clear()
        else:
            self.reason_label.setText(reason)
        self._refresh_log()

    def _fill_channels(self) -> None:
        frame = self.runner.current
        live = self.runner.state is RunState.RUNNING and self.adapter.stimulating
        commands = {c.channel: c for c in frame.commands} if frame else {}
        for row, channel in enumerate(self.opened.program.channels):
            command = commands.get(int(channel.number)) if live else None
            values = [
                f"{channel.number}",
                "Stimulating" if command else "Off",
                f"{command.pulse_width_us:g}" if command else "–",
                f"{command.amplitude_ma:g}" if command else "–",
                f"{command.frequency_hz:g}" if command else "–",
            ]
            for column, text in enumerate(values):
                item = QTableWidgetItem(text)
                item.setTextAlignment(Qt.AlignCenter)
                if column == 1:
                    bold = QFont(item.font())
                    bold.setBold(True)
                    item.setFont(bold)
                    item.setForeground(Qt.darkGreen if command else Qt.darkGray)
                self.table.setItem(row, column, item)

    def _refresh_log(self) -> None:
        records = self.adapter.command_log
        new = records[self._log_shown:]
        if new:
            self.log_view.appendPlainText(
                "\n".join(f"{r.timestamp:%H:%M:%S.%f}"[:-3] + f"  {r}" for r in new)
            )
        self._log_shown = len(records)

    def closeEvent(self, event) -> None:  # noqa: N802 (Qt name)
        """Leaving the screen never leaves stimulation running."""
        self._timer.stop()
        if self.runner.state is RunState.RUNNING:
            self.runner.stop("Stopped: execution screen closed.")
        self.wss_status_bar.stop()
        super().closeEvent(event)


def _escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
