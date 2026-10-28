"""ProgramRunner: sends a validated program to the WSS, one time step at a time.

This is the execution part of the Multi-Channel Manager (SDS 2.2): it turns a
Program into per-channel commands for the CommunicationAdapter. It follows
the program lifecycle in SDS Figure 3.3::

    READY -> RUNNING -> COMPLETE | STOPPED | ERROR

Rules it enforces, whoever calls it:

* Only a program that passed validation can run (REQ-17, SDS Fig. 3.3:
  Run is only enabled in Ready).
* Only on the fake or simulated WSS for now. The safe limits are still
  placeholders (SRS Appendix C, SDS §8), so real hardware is refused.
* ``stop()`` always works and stops output first (REQ-19).
* A lost connection ends the run in ERROR, never left running (SRS §5.2).

It does no timing itself: the caller (the Execution screen's timer) calls
:meth:`step` once per ``step_ms``. A constant program is sent once and then
held until Stop.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

#: Adapter modes a program may run on until the real limits are confirmed.
ALLOWED_MODES = ("fake", "simulated")


class RunState(str, Enum):
    READY = "Ready"
    RUNNING = "Running"
    COMPLETE = "Complete"
    STOPPED = "Stopped"
    ERROR = "Error"


class RunRefused(Exception):
    """The program can't be started. The message says why, in words."""


@dataclass(frozen=True)
class ChannelCommand:
    channel: int
    pulse_width_us: float
    amplitude_ma: float
    frequency_hz: float

    @property
    def ipi_ms(self) -> int:
        """Inter-pulse interval the WSS expects, from the frequency."""
        return max(1, round(1000.0 / self.frequency_hz))


@dataclass(frozen=True)
class Frame:
    """Everything sent at one time step."""

    index: int
    time_s: float
    commands: list[ChannelCommand] = field(default_factory=list)


class ProgramRunner:
    def __init__(self, adapter: Any, program: Any, validation: Any) -> None:
        self.adapter = adapter
        self.program = program
        self.validation = validation
        self.state = RunState.READY
        self.detail = ""
        self.position = 0  # frames sent so far
        self.frames = build_frames(program)

    # ------------------------------------------------------------ info

    @property
    def is_time_series(self) -> bool:
        return len(self.frames) > 1

    @property
    def step_ms(self) -> float:
        step = self.program.time_step_ms
        return float(step) if isinstance(step, (int, float)) and step > 0 else 0.0

    @property
    def duration_s(self) -> float:
        return self.frames[-1].time_s if self.frames else 0.0

    @property
    def current(self) -> Frame | None:
        return self.frames[self.position - 1] if self.position else None

    def why_not_runnable(self) -> str:
        """Empty if Run may be pressed, otherwise the reason, in words."""
        if self.state is RunState.RUNNING:
            return "Already running."
        if self.validation is None or not self.validation.is_valid:
            return "This program failed validation, so it can't run (fix the problems listed first)."
        if not self.frames:
            return "This program has nothing to send."
        if self.adapter is None:
            return "No WSS connection is set up."
        if self.adapter.mode not in ALLOWED_MODES:
            return (
                "Running on the real WSS isn't enabled yet: the safe limits are still "
                "placeholders and the run hasn't been checked in the lab. Use --fake."
            )
        if not self.adapter.is_connected:
            return "Connect to the WSS first."
        return ""

    # ------------------------------------------------------------ control

    def start(self) -> None:
        reason = self.why_not_runnable()
        if reason:
            raise RunRefused(reason)
        self.position = 0
        self.detail = ""
        self.state = RunState.RUNNING
        try:
            self.adapter.start_stimulation()
        except Exception as ex:
            self._fail(ex)
            return
        self._send_next()

    def step(self) -> bool:
        """Send the next time step. Returns True while the run continues."""
        if self.state is not RunState.RUNNING:
            return False
        if not self.adapter.is_connected:
            self.connection_lost("WSS connection lost")
            return False
        if self.position >= len(self.frames):
            if self.is_time_series:
                self._finish(RunState.COMPLETE, "Program finished.")
                return False
            return True  # constant program: hold until Stop
        self._send_next()
        return self.state is RunState.RUNNING

    def stop(self, reason: str = "Stopped by user.") -> None:
        """Always allowed (REQ-19). Stops output first, then records why."""
        self.adapter.stop()
        if self.state is RunState.RUNNING:
            self.state, self.detail = RunState.STOPPED, reason

    def connection_lost(self, reason: str) -> None:
        """SRS §5.2: a lost link ends the run as a stop, in the Error state."""
        if self.state is RunState.RUNNING:
            self.adapter.stop()
            self.state = RunState.ERROR
            self.detail = f"Connection lost: {reason}. Stimulation stopped."

    # ------------------------------------------------------------ helpers

    def _send_next(self) -> None:
        frame = self.frames[self.position]
        try:
            for command in frame.commands:
                self.adapter.stimulate_analog(
                    command.channel, command.pulse_width_us, command.amplitude_ma, command.ipi_ms
                )
        except Exception as ex:
            self._fail(ex)
            return
        self.position += 1
        if self.is_time_series and self.position >= len(self.frames):
            self._finish(RunState.COMPLETE, "Program finished.")

    def _finish(self, state: RunState, detail: str) -> None:
        self.adapter.stop()
        self.state, self.detail = state, detail

    def _fail(self, ex: Exception) -> None:
        self.adapter.stop()
        text = str(ex).splitlines()[0] if str(ex) else type(ex).__name__
        self.state, self.detail = RunState.ERROR, f"{text} Stimulation stopped."


def build_frames(program: Any) -> list[Frame]:
    """One Frame per time step (time-series programs) or a single Frame.

    Channels without a time series hold their constant values at every step.
    """
    channels = list(getattr(program, "channels", None) or [])
    if not channels:
        return []
    longest = max((len(c.time_series) for c in channels), default=0)
    if longest == 0:
        return [Frame(0, 0.0, [_command(c, c.pulse_width_us, c.amplitude_ma) for c in channels])]

    timeline = max(channels, key=lambda c: len(c.time_series)).time_series
    frames = []
    for index in range(longest):
        commands = []
        for c in channels:
            if c.time_series:
                point = c.time_series[min(index, len(c.time_series) - 1)]
                commands.append(_command(c, point.pulse_width_us, point.amplitude_ma))
            else:
                commands.append(_command(c, c.pulse_width_us, c.amplitude_ma))
        frames.append(Frame(index, float(timeline[index].time_s), commands))
    return frames


def _command(channel: Any, pulse_width: Any, amplitude: Any) -> ChannelCommand:
    frequency = channel.frequency_hz
    if not (isinstance(frequency, (int, float)) and math.isfinite(frequency) and frequency > 0):
        frequency = 1.0  # only reachable for programs that failed validation
    return ChannelCommand(int(channel.number), pulse_width, amplitude, float(frequency))
