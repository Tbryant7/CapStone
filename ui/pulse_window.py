"""Test Pulse Window (Sprint 1).

A small PySide6 window that proves the app can control the WSS end to end:
pick a serial port, connect, send one test pulse train on channel 1 with
fixed safe values, and stop it. It only talks to the WSS through a
``CommunicationAdapter``, so it runs the same way with real hardware, the
wrapper's simulated transport or the pure-Python fake.
"""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from comms import AdapterStatus, CommunicationAdapter, ConnectionState

from .serial_ports import list_serial_ports
from .wss_status_bar import WssStatusBar

#: Fixed values for the test pulse. Deliberately low.
#: TODO(Sprint 2): confirm these and their units against the COSMIIC safe
#: ranges (validation/ranges.json) before running on a person.
TEST_CHANNEL = 1
TEST_PULSE_WIDTH = 50
TEST_AMPLITUDE = 1
TEST_IPI = 50

#: How often the window asks the adapter whether the WSS is still there (ms).
CONNECTION_CHECK_MS = 1000

AUTO_DETECT = "Auto-detect"


class _StatusBridge(QObject):
    """Adapter listeners can run on other threads (e.g. the fake timer).
    Re-emitting through a Qt signal moves the update onto the GUI thread."""

    changed = Signal(object)


class TestPulseWindow(QMainWindow):
    def __init__(
        self,
        adapter: CommunicationAdapter,
        port_lister: Callable[[], list[str]] = list_serial_ports,
    ) -> None:
        super().__init__()
        self.adapter = adapter
        self._port_lister = port_lister
        self._log_shown = 0
        self._simulated = adapter.mode != "hardware"
        self._lost_reason = ""

        self.setWindowTitle("COSMIIC WSS: Test Pulse")
        self.setMinimumSize(560, 520)
        self._build()

        self._bridge = _StatusBridge()
        self._bridge.changed.connect(self._on_status)
        adapter.add_status_listener(self._bridge.changed.emit)

        self._timer = QTimer(self)
        self._timer.setInterval(CONNECTION_CHECK_MS)
        self._timer.timeout.connect(self._tick)
        self._timer.start()

        self.refresh_ports()
        self._refresh_view()

    # ------------------------------------------------------------- layout

    def _build(self) -> None:
        root = QWidget()
        outer = QVBoxLayout(root)
        outer.setContentsMargins(16, 16, 16, 16)
        outer.setSpacing(12)

        # Mode banner: always say in words when nothing real is connected.
        self.mode_label = QLabel()
        self.mode_label.setObjectName("modeLabel")
        if self._simulated:
            self.mode_label.setText(
                f"SIMULATED ({self.adapter.mode} mode): no stimulation reaches a person"
            )
        else:
            self.mode_label.setText("HARDWARE mode: commands go to the real WSS")
        outer.addWidget(self.mode_label)

        # Connection row
        grid = QGridLayout()
        grid.addWidget(QLabel("Serial port:"), 0, 0)
        self.port_combo = QComboBox()
        self.port_combo.setMinimumWidth(180)
        grid.addWidget(self.port_combo, 0, 1)
        self.refresh_button = QPushButton("Refresh")
        self.refresh_button.clicked.connect(self.refresh_ports)
        grid.addWidget(self.refresh_button, 0, 2)
        self.connect_button = QPushButton("Connect")
        self.connect_button.clicked.connect(self.toggle_connection)
        grid.addWidget(self.connect_button, 0, 3)

        grid.addWidget(QLabel("Status:"), 1, 0)
        self.status_label = QLabel()
        self.status_label.setObjectName("statusLabel")
        grid.addWidget(self.status_label, 1, 1, 1, 3)

        grid.addWidget(QLabel("Output:"), 2, 0)
        self.output_label = QLabel()
        grid.addWidget(self.output_label, 2, 1, 1, 3)
        grid.setColumnStretch(1, 1)
        outer.addLayout(grid)

        outer.addWidget(_line())

        # Test pulse
        values = QLabel(
            f"Test pulse: channel {TEST_CHANNEL}, pulse width {TEST_PULSE_WIDTH}, "
            f"amplitude {TEST_AMPLITUDE}, interval {TEST_IPI} (fixed)"
        )
        values.setWordWrap(True)
        outer.addWidget(values)

        buttons = QHBoxLayout()
        self.pulse_button = QPushButton("Send Test Pulse")
        self.pulse_button.setMinimumHeight(48)
        self.pulse_button.clicked.connect(self.send_test_pulse)
        buttons.addWidget(self.pulse_button, 1)

        self.stop_button = QPushButton("STOP")
        self.stop_button.setObjectName("stopButton")
        self.stop_button.setMinimumHeight(48)
        self.stop_button.setToolTip("Stop all stimulation (always available)")
        self.stop_button.clicked.connect(self.stop)
        buttons.addWidget(self.stop_button, 1)
        outer.addLayout(buttons)

        self.drop_button = QPushButton("Simulate disconnect")
        self.drop_button.setToolTip("Pretend the WSS was unplugged (simulated modes only)")
        self.drop_button.clicked.connect(self.simulate_disconnect)
        self.drop_button.setVisible(self.adapter.supports_fake_disconnect)
        outer.addWidget(self.drop_button, 0, Qt.AlignLeft)

        self.message_label = QLabel()
        self.message_label.setObjectName("messageLabel")
        self.message_label.setWordWrap(True)
        self.message_label.setVisible(False)
        outer.addWidget(self.message_label)

        outer.addWidget(QLabel("Command log:"))
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        mono = QFont("Consolas")
        mono.setStyleHint(QFont.Monospace)
        self.log_view.setFont(mono)
        outer.addWidget(self.log_view, 1)

        self.setCentralWidget(root)

        # WSS status bar (Sprint 2), the same widget the main window will use.
        self.wss_status_bar = WssStatusBar(self.adapter, port_lister=self._port_lister)
        self.setStatusBar(self.wss_status_bar)
        self.setStyleSheet(
            """
            #modeLabel { padding: 6px 10px; border-radius: 4px; font-weight: bold;
                         background: %s; color: #1a1a1a; }
            #stopButton { background: #c62828; color: white; font-weight: bold;
                          font-size: 16px; border-radius: 6px; }
            #stopButton:pressed { background: #8e0000; }
            #messageLabel { color: #b71c1c; }
            """
            % ("#ffe082" if self._simulated else "#c8e6c9")
        )

    # ------------------------------------------------------------ actions

    def refresh_ports(self) -> None:
        self.port_combo.clear()
        if self._simulated:
            self.port_combo.addItem("Simulated WSS (no port)")
            self.port_combo.setEnabled(False)
            self.refresh_button.setEnabled(False)
            return
        self.port_combo.addItem(AUTO_DETECT)
        for name in self._port_lister():
            self.port_combo.addItem(name)

    def selected_port(self) -> str | None:
        if self._simulated or self.port_combo.currentText() == AUTO_DETECT:
            return None
        return self.port_combo.currentText() or None

    def toggle_connection(self) -> None:
        if self.adapter.is_connected:
            self._attempt(self.adapter.disconnect)
        else:
            self._attempt(lambda: self.adapter.connect(self.selected_port()))

    def send_test_pulse(self) -> None:
        self._attempt(
            lambda: self.adapter.send_test_pulse(
                TEST_CHANNEL, TEST_PULSE_WIDTH, TEST_AMPLITUDE, TEST_IPI
            )
        )

    def stop(self) -> None:
        self._attempt(self.adapter.stop)

    def simulate_disconnect(self) -> None:
        self._attempt(lambda: self.adapter.simulate_disconnect("simulated disconnect"))

    def _attempt(self, action: Callable[[], None]) -> None:
        """Run an adapter call; show any error as a message instead of crashing."""
        self.message_label.clear()
        try:
            action()
        except Exception as ex:  # wrong port, unplugged device, .NET missing ...
            first_line = str(ex).splitlines()[0] if str(ex) else type(ex).__name__
            self.message_label.setText(f"Error: {first_line}")
        self.message_label.setVisible(bool(self.message_label.text()))
        self._refresh_view()

    def _tick(self) -> None:
        self.adapter.check_connection()
        self._refresh_log()

    # ------------------------------------------------------------ display

    def _on_status(self, status: AdapterStatus) -> None:
        """Called (on the GUI thread) whenever the adapter reports a change."""
        if status.state is ConnectionState.LOST:
            self._lost_reason = status.detail
        self._refresh_view()

    def _refresh_view(self) -> None:
        state = self.adapter.status().state  # read the latest, not a stale copy
        connected = state is ConnectionState.CONNECTED

        if connected:
            text, color = "Connected", "#2e7d32"
        elif state is ConnectionState.LOST:
            reason = f": {self._lost_reason}" if self._lost_reason else ""
            text, color = f"Connection lost{reason}", "#c62828"
        else:
            text, color = "Not connected", "#616161"
        self.status_label.setText(text)
        self.status_label.setStyleSheet(f"color: {color}; font-weight: bold;")

        stimulating = self.adapter.stimulating
        self.output_label.setText(
            f"Stimulating on channel {TEST_CHANNEL}" if stimulating else "Off"
        )
        self.output_label.setStyleSheet("font-weight: bold;" if stimulating else "")

        self.connect_button.setText("Disconnect" if connected else "Connect")
        self.pulse_button.setEnabled(connected)
        self.drop_button.setEnabled(connected)
        self.port_combo.setEnabled(not connected and not self._simulated)
        self._refresh_log()

    def _refresh_log(self) -> None:
        records = self.adapter.command_log
        for record in records[self._log_shown:]:
            self.log_view.appendPlainText(f"{record.timestamp:%H:%M:%S}  {record}")
        self._log_shown = len(records)

    def closeEvent(self, event) -> None:  # noqa: N802 (Qt name)
        self._timer.stop()
        self.wss_status_bar.stop()
        if self.adapter.is_connected:
            try:
                self.adapter.disconnect()  # stops stimulation first
            except Exception:
                pass
        super().closeEvent(event)


def _line() -> QFrame:
    line = QFrame()
    line.setFrameShape(QFrame.HLine)
    line.setFrameShadow(QFrame.Sunken)
    return line
