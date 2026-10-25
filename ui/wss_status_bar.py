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
from PySide6.QtWidgets import QLabel, QStatusBar

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
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.adapter = adapter
        self._port_lister = port_lister
        self._simulated = adapter.mode != "hardware"
        self._lost_reason = ""
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

        if state is ConnectionState.CONNECTED:
            count = self.adapter.channel_count()
            self.channels_label.setText(
                "Channels: unknown" if count is None
                else f"Channels: {count}"
            )
        else:
            self.channels_label.setText("Channels: none (not connected)")

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
