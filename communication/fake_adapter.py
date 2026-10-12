"""Pure-Python stand-in for the WSS. No .NET, no DLLs, no hardware.

Use this on any laptop (Mac, Linux or Windows) when you just want the app to
run. It keeps a small model of what the stimulator would be doing, so the GUI
and tests can check the result of a command, not only that it was sent.
"""

from __future__ import annotations

import threading

from .base import CommunicationAdapter


class FakeCommunicationAdapter(CommunicationAdapter):
    """Accepts the same commands as the real adapter, logs them and sends nothing.

    Ways to test connection loss:

    * ``simulate_disconnect()``: drop the link right now.
    * ``disconnect_after_commands=N``: drop the link automatically once N
      commands have succeeded. This makes "fails mid-program" tests repeatable.
    * ``disconnect_after_seconds=T``: drop the link on a timer T seconds
      after ``connect()``. This is useful for trying it by hand in the GUI.
    """

    mode = "fake"
    supports_fake_disconnect = True

    def __init__(
        self,
        disconnect_after_commands: int | None = None,
        disconnect_after_seconds: float | None = None,
    ) -> None:
        super().__init__()
        self._disconnect_after_commands = disconnect_after_commands
        self._disconnect_after_seconds = disconnect_after_seconds
        self._commands_sent = 0
        self._timer: threading.Timer | None = None
        #: Last value sent to each channel, e.g. {2: {"magnitude": 0.5}}.
        self.channel_outputs: dict[int, dict[str, float]] = {}

    # backend hooks -------------------------------------------------------

    def _do_connect(self) -> None:
        self._commands_sent = 0
        if self._disconnect_after_seconds is not None:
            self._timer = threading.Timer(
                self._disconnect_after_seconds,
                self.simulate_disconnect,
                kwargs={"reason": f"timed fake disconnect after {self._disconnect_after_seconds}s"},
            )
            self._timer.daemon = True
            self._timer.start()

    def _do_disconnect(self) -> None:
        self._cancel_timer()
        self.channel_outputs.clear()

    def _do_start(self) -> None:
        pass

    def _do_stop(self) -> None:
        self.channel_outputs.clear()

    def _do_stimulate(self, channel: int, magnitude: float) -> None:
        self.channel_outputs[channel] = {"magnitude": magnitude}

    def _do_stimulate_analog(self, channel: int, pw: int, amp: int, ipi: int) -> None:
        self.channel_outputs[channel] = {"pulse_width": pw, "amplitude": amp, "ipi": ipi}

    def _on_simulated_disconnect(self) -> None:
        self._cancel_timer()
        self.channel_outputs.clear()

    def _status_detail(self) -> str:
        return f"{self._commands_sent} commands accepted"

    # helpers --------------------------------------------------------------

    def _after_command(self, command: str) -> None:
        if command in ("connect", "disconnect"):
            return
        self._commands_sent += 1
        limit = self._disconnect_after_commands
        if limit is not None and self._commands_sent >= limit and self.is_connected:
            # The command that reaches the limit still succeeds. The next one
            # fails, just like a link that drops between two packets.
            self.simulate_disconnect(f"fake disconnect after {limit} commands")

    def _cancel_timer(self) -> None:
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None
