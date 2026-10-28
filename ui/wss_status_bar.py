"""WSS status bar (Sprint 2): always shows whether the WSS is connected and how
many channels it reports.

Drop it into any QMainWindow::

    window.setStatusBar(WssStatusBar(adapter))

It updates the moment the adapter reports a change (connect, disconnect,
lost) and also checks the link every couple of seconds, so an unplugged WSS
shows up within a few seconds. Every state is written in words; color is only
an extra cue.
"""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtWidgets import QLabel, QPushButton, QStatusBar

from comms import AdapterStatus, CommunicationAdapter, ConnectionState

from .serial_ports import list_serial_ports

#: How often to re-check the connection and channel count (ms).
CHECK_INTERVAL_MS = 2000

STATE_TEXT = {
    ConnectionState.CONNECTED: "WSS: Connected",
    ConnectionState.DISCONNECTED: "WSS: Not connected",
    ConnectionState.LOST: "WSS: Connection lost",
}
STATE_COLOR = {
    ConnectionState.CONNECTED: "#2e7d32",
    ConnectionState.DISCONNECTED: "#616161",
    ConnectionState.LOST: "#c62828",
}


class _Bridge(QObject):
    """Adapter listeners may run on other threads; this moves updates to the GUI thread."""

    changed = Signal(object)


class WssStatusBar(QStatusBar):
    def __init__(
        self,
        adapter: CommunicationAdapter,
        check_interval_ms: int = CHECK_INTERVAL_MS,
        port_lister: Callable[[], list[str]] = list_serial_ports,
        show_connect_button: bool = False,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.adapter = adapter
        self._port_lister = port_lister
        self._simulated = adapter.mode != "hardware"
        self._lost_reason = ""
        #: Channel numbers of the opened program, shown next to the device count.
        self._program_channels: list[int] | None = None
        self.setSizeGripEnabled(False)

        self.state_label = QLabel()
        self.state_label.setObjectName("wssState")
        self.channels_label = QLabel()
        self.channels_label.setObjectName("wssChannels")
        self.mode_label = QLabel()
        self.mode_label.setObjectName("wssMode")
        if self._simulated:
            self.mode_label.setText(f"SIMULATED ({adapter.mode} mode)")
            self.mode_label.setStyleSheet(
                "background: #ffe082; color: #1a1a1a; padding: 1px 6px; font-weight: bold;"
            )
        else:
            self.mode_label.setText("Hardware")

        self.addWidget(self.state_label)
        self.addWidget(_separator())
        self.addWidget(self.channels_label)
        self.addPermanentWidget(self.mode_label)

        #: Optional Connect/Disconnect button, for windows that have no
        #: connection controls of their own (e.g. the Main Menu).
        self.connect_button: QPushButton | None = None
        self.error_label = QLabel()
        self.error_label.setObjectName("wssError")
        self.error_label.setStyleSheet("color: #c62828;")
        self.error_label.setVisible(False)
        self.addWidget(self.error_label)
        if show_connect_button:
            self.connect_button = QPushButton("Connect")
            self.connect_button.setObjectName("wssConnectButton")
            self.connect_button.clicked.connect(self.toggle_connection)
            self.addPermanentWidget(self.connect_button)

        self._bridge = _Bridge()
        self._bridge.changed.connect(self._on_status)
        adapter.add_status_listener(self._bridge.changed.emit)

        self._timer = QTimer(self)
        self._timer.setInterval(check_interval_ms)
        self._timer.timeout.connect(self._tick)
        self._timer.start()

        self.refresh()

    # ----------------------------------------------------------- updates

    def _on_status(self, status: AdapterStatus) -> None:
        if status.state is ConnectionState.LOST:
            self._lost_reason = status.detail
        self.refresh()

    def set_program_channels(self, numbers: list[int] | None) -> None:
        """Show which channels the opened program uses (None hides it)."""
        self._program_channels = list(numbers) if numbers is not None else None
        self.refresh()

    def toggle_connection(self) -> None:
        """Connect, or disconnect (which always stops stimulation first)."""
        self.error_label.setVisible(False)
        try:
            if self.adapter.is_connected:
                self.adapter.disconnect()
            else:
                self.adapter.connect()
        except Exception as ex:  # wrong port, unplugged, .NET missing ...
            text = str(ex).splitlines()[0] if str(ex) else type(ex).__name__
            self.error_label.setText(f"Could not connect: {text}")
            self.error_label.setVisible(True)
        self.refresh()

    def _tick(self) -> None:
        """Timer: notice an unplugged WSS and pick up channel-count changes."""
        self.adapter.check_connection()
        self.refresh()

    def refresh(self) -> None:
        state = self.adapter.status().state

        text = STATE_TEXT[state]
        if state is ConnectionState.LOST and self._lost_reason:
            text += f" ({self._lost_reason})"
        elif state is ConnectionState.DISCONNECTED and not self._simulated:
            ports = self._safe_ports()
            text += (f" (serial device found: {', '.join(ports)})" if ports
                     else " (no serial device found)")
        self.state_label.setText(text)
        self.state_label.setStyleSheet(f"color: {STATE_COLOR[state]}; font-weight: bold;")

        count = self.adapter.channel_count() if state is ConnectionState.CONNECTED else None
        if state is ConnectionState.CONNECTED:
            device = "Channels: unknown" if count is None else f"Channels: {count} on WSS"
        else:
            device = "Channels: none (not connected)"

        style = ""
        if self._program_channels is not None:
            used = self._program_channels
            device += f" · program uses {len(used)} ({', '.join(str(n) for n in used)})"
            missing = (
                [n for n in used if not 1 <= n <= count] if count is not None else []
            )
            if missing:
                device += f" · not on this WSS: {', '.join(str(n) for n in missing)}"
                style = "color: #c62828; font-weight: bold;"
        self.channels_label.setText(device)
        self.channels_label.setStyleSheet(style)

        if self.connect_button is not None:
            self.connect_button.setText(
                "Disconnect" if state is ConnectionState.CONNECTED else "Connect"
            )

    def text(self) -> str:
        """Everything the bar shows, as one line (handy for tests and logs)."""
        return " | ".join(
            label.text() for label in (self.state_label, self.channels_label, self.mode_label)
        )

    def stop(self) -> None:
        self._timer.stop()

    def _safe_ports(self) -> list[str]:
        try:
            return list(self._port_lister())
        except Exception:
            return []


def _separator() -> QLabel:
    sep = QLabel("|")
    sep.setStyleSheet("color: #9e9e9e;")
    return sep
