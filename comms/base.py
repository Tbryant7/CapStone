"""Base class shared by every Communication Adapter.

The Communication Adapter is the only part of the app that talks to the WSS
(see SRS Figure 2.2). Everything above it -- the GUI, validation, the
multi-channel manager -- calls the methods defined here and never imports the
wrapper directly. That is what lets us swap real hardware for a simulation with
a single setting.

This base class owns three things every adapter must do identically:

1. Log every command it receives (with arguments and outcome).
2. Track connection state and refuse commands while disconnected.
3. Support a fake disconnect in simulated modes, so error handling
   (SRS use case "Import and Execute", alternate flow A3) can be tested
   without unplugging anything.

Subclasses only implement the ``_do_*`` methods that actually move data.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable

logger = logging.getLogger("wss_comm")

#: Inter-pulse interval used by ``send_test_pulse`` when none is given.
DEFAULT_TEST_IPI = 50


class ConnectionState(str, Enum):
    DISCONNECTED = "disconnected"
    CONNECTED = "connected"
    LOST = "lost"  # connection dropped unexpectedly (real or simulated)


class ConnectionLostError(RuntimeError):
    """Raised when a command is sent while the adapter is not connected."""


@dataclass(frozen=True)
class CommandRecord:
    """One logged command. Kept in memory so tests and the GUI can inspect it."""

    timestamp: datetime
    command: str
    args: dict[str, Any]
    outcome: str  # "ok", "rejected: <reason>" or "error: <message>"

    def __str__(self) -> str:
        arg_text = " ".join(f"{k}={v}" for k, v in self.args.items())
        return f"{self.command}({arg_text}) -> {self.outcome}"


@dataclass(frozen=True)
class AdapterStatus:
    mode: str
    state: ConnectionState
    stimulating: bool
    detail: str = ""


StatusListener = Callable[[AdapterStatus], None]


@dataclass
class _CommandLog:
    records: list[CommandRecord] = field(default_factory=list)
    lock: threading.Lock = field(default_factory=threading.Lock)


class CommunicationAdapter:
    """Common interface for talking to the WSS.

    Public methods (``connect``, ``stimulate`` ...) are what the rest of the
    app calls. Each one is routed through :meth:`_run`, which does the logging
    and connection checks, then calls the subclass's ``_do_*`` hook.

    Channels are plain integers starting at 1. No maximum is hard-coded here
    (SRS REQ-23); range checks belong in the Validation & Safety Engine.
    """

    mode: str = "base"
    #: Only simulated adapters may fake a disconnect. Never on real hardware.
    supports_fake_disconnect: bool = False

    def __init__(self) -> None:
        self._state = ConnectionState.DISCONNECTED
        self._stimulating = False
        self._log = _CommandLog()
        self._listeners: list[StatusListener] = []
        self._state_lock = threading.Lock()

    # ------------------------------------------------------------------ API

    def connect(self, port: str | None = None) -> None:
        """Open the link to the WSS.

        :param port: Serial port to use (for example ``"COM3"``). ``None``
            keeps the port from the config, or auto-detects it.
        """
        args = {} if port is None else {"port": port}

        def action() -> None:
            if port is not None:
                self._set_port(port)
            self._do_connect()

        self._run("connect", args, action, require_connection=False)
        self._set_state(ConnectionState.CONNECTED, "connected")

    def disconnect(self) -> None:
        """Normal, intentional shutdown. Always stops stimulation first."""
        if self.is_connected:
            self._run("stop_stimulation", {"reason": "disconnect"}, self._do_stop)
            self._stimulating = False
        self._run("disconnect", {}, self._do_disconnect, require_connection=False)
        self._set_state(ConnectionState.DISCONNECTED, "disconnected")

    def start_stimulation(self) -> None:
        def action() -> None:
            self._do_start()
            self._stimulating = True

        self._run("start_stimulation", {}, action)
        self._notify()

    def stop_stimulation(self) -> None:
        # Stop is safety-critical (SRS REQ-19): it is logged even when
        # disconnected, and never raises just because the link is down.
        if not self.is_connected:
            self._record("stop_stimulation", {}, "rejected: not connected (no output possible)")
            self._stimulating = False
            self._notify()
            return
        self._run("stop_stimulation", {}, self._do_stop)
        self._stimulating = False
        self._notify()

    def stimulate(self, channel: int, magnitude: float) -> None:
        """Stimulate a channel with a normalized magnitude (0.0 to 1.0).

        The wrapper's params layer maps this onto pulse width or amplitude
        using ``stimParams.json``.
        """
        self._check_channel(channel)
        self._run(
            "stimulate",
            {"channel": channel, "magnitude": magnitude},
            lambda: self._do_stimulate(channel, magnitude),
        )

    def stimulate_analog(
        self, channel: int, pulse_width: int, amplitude: int, ipi: int
    ) -> None:
        """Send explicit pulse width / amplitude / inter-pulse interval."""
        self._check_channel(channel)
        self._run(
            "stimulate_analog",
            {"channel": channel, "pulse_width": pulse_width, "amplitude": amplitude, "ipi": ipi},
            lambda: self._do_stimulate_analog(channel, pulse_width, amplitude, ipi),
        )

    def send_test_pulse(
        self, channel: int, pulse_width: int, amplitude: int, ipi: int = DEFAULT_TEST_IPI
    ) -> None:
        """Deliver a test pulse train on one channel (Sprint 1 Test Pulse Window).

        Starts stimulation if it is not already running, then sends the
        explicit pulse width / amplitude / inter-pulse interval. Call
        :meth:`stop` to end it.
        """
        if not self._stimulating:
            self.start_stimulation()
        self.stimulate_analog(channel, pulse_width, amplitude, ipi)

    def stop(self) -> None:
        """Stop all stimulation. Same as :meth:`stop_stimulation`; never raises
        because the link is down (SRS REQ-19)."""
        self.stop_stimulation()

    def check_connection(self) -> bool:
        """Ask the backend whether the link is still alive.

        The GUI calls this every second or so. If a connected adapter finds
        the device gone (for example the WSS was unplugged), the state
        switches to ``LOST`` and status listeners are told, exactly like a
        fake disconnect. Returns ``is_connected`` after the check.
        """
        if not self.is_connected:
            return False
        try:
            alive = self._is_alive()
            reason = "WSS stopped responding"
        except Exception as ex:
            alive, reason = False, f"WSS check failed: {ex}"
        if not alive and self.is_connected:
            self._record("check_connection", {}, f"lost: {reason}")
            logger.warning("[%s] connection LOST: %s", self.mode, reason)
            self._stimulating = False
            self._set_state(ConnectionState.LOST, reason)
        return self.is_connected

    @property
    def stimulating(self) -> bool:
        return self._stimulating

    def status(self) -> AdapterStatus:
        return AdapterStatus(self.mode, self._state, self._stimulating, self._status_detail())

    # -------------------------------------------------------- fake disconnect

    def simulate_disconnect(self, reason: str = "simulated connection loss") -> None:
        """Pretend the link to the WSS just dropped.

        After this, every command except ``stop_stimulation`` raises
        :class:`ConnectionLostError` until :meth:`connect` is called again.
        Status listeners are told immediately, the same way they would be on
        a real failure.
        """
        if not self.supports_fake_disconnect:
            raise RuntimeError(f"Fake disconnect is not allowed in '{self.mode}' mode.")
        self._record("simulate_disconnect", {"reason": reason}, "ok")
        logger.warning("[%s] connection LOST: %s", self.mode, reason)
        self._on_simulated_disconnect()
        self._stimulating = False
        self._set_state(ConnectionState.LOST, reason)

    # --------------------------------------------------------------- queries

    @property
    def is_connected(self) -> bool:
        return self._state is ConnectionState.CONNECTED

    @property
    def command_log(self) -> list[CommandRecord]:
        with self._log.lock:
            return list(self._log.records)

    def add_status_listener(self, listener: StatusListener) -> None:
        """Register a callback (e.g. the GUI status bar) for state changes."""
        self._listeners.append(listener)

    # ---------------------------------------------------- hooks for subclasses

    def _do_connect(self) -> None:
        raise NotImplementedError

    def _do_disconnect(self) -> None:
        raise NotImplementedError

    def _do_start(self) -> None:
        raise NotImplementedError

    def _do_stop(self) -> None:
        raise NotImplementedError

    def _do_stimulate(self, channel: int, magnitude: float) -> None:
        raise NotImplementedError

    def _do_stimulate_analog(self, channel: int, pw: int, amp: int, ipi: int) -> None:
        raise NotImplementedError

    def _set_port(self, port: str) -> None:
        """Optional: use ``port`` for the next connect. Default ignores it."""

    def _is_alive(self) -> bool:
        """Optional: return False if the device has gone away. Default: alive."""
        return True

    def _on_simulated_disconnect(self) -> None:
        """Optional: backend-specific work when a fake disconnect happens."""

    def _status_detail(self) -> str:
        return ""

    def _after_command(self, command: str) -> None:
        """Optional: runs after a command succeeded and was logged."""

    # -------------------------------------------------------------- internals

    def _run(
        self,
        command: str,
        args: dict[str, Any],
        action: Callable[[], None],
        require_connection: bool = True,
    ) -> None:
        if require_connection and not self.is_connected:
            reason = "connection lost" if self._state is ConnectionState.LOST else "not connected"
            self._record(command, args, f"rejected: {reason}")
            raise ConnectionLostError(f"Cannot send '{command}': {reason}.")
        try:
            action()
        except Exception as ex:
            self._record(command, args, f"error: {ex}")
            raise
        self._record(command, args, "ok")
        self._after_command(command)

    def _record(self, command: str, args: dict[str, Any], outcome: str) -> None:
        record = CommandRecord(datetime.now(), command, dict(args), outcome)
        with self._log.lock:
            self._log.records.append(record)
        level = logging.INFO if outcome == "ok" else logging.WARNING
        logger.log(level, "[%s] %s", self.mode, record)

    def _set_state(self, state: ConnectionState, detail: str) -> None:
        with self._state_lock:
            self._state = state
        self._notify(detail)

    def _notify(self, detail: str = "") -> None:
        status = AdapterStatus(self.mode, self._state, self._stimulating, detail)
        for listener in list(self._listeners):
            try:
                listener(status)
            except Exception:  # a broken listener must never break stimulation control
                logger.exception("Status listener failed")

    @staticmethod
    def _check_channel(channel: int) -> None:
        if not isinstance(channel, int) or isinstance(channel, bool) or channel < 1:
            raise ValueError(f"Channel must be a positive integer, got {channel!r}.")
