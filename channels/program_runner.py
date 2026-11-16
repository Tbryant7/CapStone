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
* After the user stops a time series, it can **resume** from where it
  stopped instead of starting over. STOP itself still turns output off at
  once; resuming is a separate, deliberate choice afterwards. It ramps the
  amplitude back up from 0 over ``RESUME_RAMP_S`` instead of jumping straight
  to the stopped values, re-checks everything Run checks, and is not offered
  after a lost connection, an error, or a finished program.

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

#: When resuming, amplitude ramps from 0 back to the program's value over
#: this many seconds (pulse width and frequency are sent as they are).
RESUME_RAMP_S = 1.0


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
        #: Frame index a stopped run can resume from (None: nothing to resume).
        self._resume_at: int | None = None
        #: Ramp-up frames still to send before the program continues.
        self._ramp: list[Frame] = []
        self.ramp_total = 0
        self._last_sent: Frame | None = None

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
        """What is being output now (a ramp-up frame while resuming)."""
        return self._last_sent

    @property
    def resume_time_s(self) -> float | None:
        """Where Resume would continue from, or None if there's nothing to resume."""
        if self._resume_at is None or self.state is RunState.RUNNING:
            return None
        return self.frames[self._resume_at].time_s

    @property
    def is_ramping(self) -> bool:
        return self.state is RunState.RUNNING and bool(self._ramp)

    @property
    def ramp_position(self) -> int:
        """Ramp-up frames sent so far (while resuming)."""
        return self.ramp_total - len(self._ramp)

    @property
    def resume_target_s(self) -> float | None:
        """Program time the ramp is heading for (while resuming)."""
        return self.frames[self.position].time_s if self._ramp else None

    def why_not_runnable(self) -> str:
        """Empty if Run may be pressed, otherwise the reason, in words."""
        if self.state is RunState.RUNNING:
            return "Already running."
        return self._checks()

    def why_not_resumable(self) -> str:
        """Empty if Resume may be pressed, otherwise the reason, in words."""
        if self.state is RunState.RUNNING:
            return "Already running."
        if self._resume_at is None:
            return "There's nothing to resume: Run starts from the beginning."
        return self._checks()

    def _checks(self) -> str:
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
        missing = unavailable_channels(self.program, self.adapter.channel_count())
        if missing:
            return channel_mismatch_message(missing, self.adapter.channel_count())
        return ""

    # ------------------------------------------------------------ control

    def start(self) -> None:
        """Run from the beginning (also "Restart from 0 s" after a stop)."""
        reason = self.why_not_runnable()
        if reason:
            raise RunRefused(reason)
        self.position = 0
        self.detail = ""
        self._forget_resume()
        self.state = RunState.RUNNING
        try:
            self.adapter.start_stimulation()
        except Exception as ex:
            self._fail(ex)
            return
        self._send_next()

    def resume(self) -> None:
        """Continue a stopped time series from where it stopped, ramping
        the amplitude back up from 0 over RESUME_RAMP_S first."""
        reason = self.why_not_resumable()
        if reason:
            raise RunRefused(reason)
        self.position = self._resume_at
        target = self.frames[self.position]
        steps = max(1, round(RESUME_RAMP_S * 1000.0 / self.step_ms)) if self.step_ms else 1
        self._ramp = ramp_frames(target, steps)
        self.ramp_total = len(self._ramp)
        self._resume_at = None
        self.detail = (f"Resumed at t = {target.time_s:g} s: amplitude ramps back up "
                       f"over {RESUME_RAMP_S:g} s, then the program continues.")
        self.state = RunState.RUNNING
        try:
            self.adapter.start_stimulation()
        except Exception as ex:
            self._fail(ex)
            return
        self._send_ramp() if self._ramp else self._send_next()

    def step(self) -> bool:
        """Send the next time step. Returns True while the run continues."""
        if self.state is not RunState.RUNNING:
            return False
        if not self.adapter.is_connected:
            self.connection_lost("WSS connection lost")
            return False
        if self._ramp:
            self._send_ramp()
            return self.state is RunState.RUNNING
        if self.position >= len(self.frames):
            if self.is_time_series:
                self._finish(RunState.COMPLETE, "Program finished.")
                return False
            return True  # constant program: hold until Stop
        self._send_next()
        return self.state is RunState.RUNNING

    def stop(self, reason: str = "Stopped by user.") -> None:
        """Always allowed (REQ-19). Stops output first, then records why.

        A time series stopped part way can be resumed later: it continues
        with the step that was cut off (or the one a ramp was heading for)."""
        self.adapter.stop()
        if self.state is RunState.RUNNING:
            self.state, self.detail = RunState.STOPPED, reason
            if self.is_time_series and self.position < len(self.frames):
                self._resume_at = self.position if self._ramp else max(self.position - 1, 0)
                self.detail = (f"{reason.rstrip('.')} at t = {self.frames[self._resume_at].time_s:g} s "
                               f"of {self.duration_s:g} s. Output is off.")
            self._ramp = []
            self._last_sent = None

    def connection_lost(self, reason: str) -> None:
        """SRS §5.2: a lost link ends the run as a stop, in the Error state.
        Whatever was stopped can't be resumed after this, only restarted."""
        self._forget_resume()
        if self.state is RunState.RUNNING:
            self.adapter.stop()
            self.state = RunState.ERROR
            self.detail = f"Connection lost: {reason}. Stimulation stopped."

    # ------------------------------------------------------------ helpers

    def _send(self, frame: Frame) -> bool:
        try:
            for command in frame.commands:
                self.adapter.stimulate_analog(
                    command.channel, command.pulse_width_us, command.amplitude_ma, command.ipi_ms
                )
        except Exception as ex:
            self._fail(ex)
            return False
        self._last_sent = frame
        return True

    def _send_ramp(self) -> None:
        self._send(self._ramp.pop(0))

    def _forget_resume(self) -> None:
        self._resume_at = None
        self._ramp = []
        self.ramp_total = 0

    def _send_next(self) -> None:
        if not self._send(self.frames[self.position]):
            return
        self.position += 1
        if self.is_time_series and self.position >= len(self.frames):
            self._finish(RunState.COMPLETE, "Program finished.")

    def _finish(self, state: RunState, detail: str) -> None:
        self.adapter.stop()
        self._forget_resume()
        self._last_sent = None
        self.state, self.detail = state, detail

    def _fail(self, ex: Exception) -> None:
        self.adapter.stop()
        self._forget_resume()
        self._last_sent = None
        text = str(ex).splitlines()[0] if str(ex) else type(ex).__name__
        self.state, self.detail = RunState.ERROR, f"{text} Stimulation stopped."


def ramp_frames(target: Frame, steps: int) -> list[Frame]:
    """Frames that take the amplitude from near 0 up toward ``target``'s.

    ``steps`` frames at 1/(steps+1) ... steps/(steps+1) of each channel's
    amplitude (pulse width and frequency as in the target); the target frame
    itself is sent next, at full value."""
    return [
        Frame(target.index, target.time_s, [
            ChannelCommand(c.channel, c.pulse_width_us,
                           round(c.amplitude_ma * k / (steps + 1), 3), c.frequency_hz)
            for c in target.commands
        ])
        for k in range(1, steps + 1)
    ]


def program_channel_numbers(program: Any) -> list[int]:
    """The channel numbers a program uses, in order (whole numbers only)."""
    numbers = []
    for channel in getattr(program, "channels", None) or []:
        n = channel.number
        if isinstance(n, (int, float)) and not isinstance(n, bool) and float(n).is_integer():
            numbers.append(int(n))
    return numbers


def unavailable_channels(program: Any, device_channels: int | None) -> list[int]:
    """Channels the program uses that the connected WSS doesn't report
    (REQ-21, SRS "Configure Multiple Channels" A1). Empty when the device
    count is unknown: the WSS itself still rejects channels it doesn't have."""
    if device_channels is None:
        return []
    return [n for n in program_channel_numbers(program) if not 1 <= n <= device_channels]


def channel_mismatch_message(missing: list[int], device_channels: int | None) -> str:
    names = ", ".join(str(n) for n in missing)
    word = "Channel" if len(missing) == 1 else "Channels"
    verb = "isn't" if len(missing) == 1 else "aren't"
    return (
        f"{word} {names} {verb} available on the connected WSS "
        f"(it reports {device_channels} channel{'s' if device_channels != 1 else ''})."
    )


def build_frames(program: Any) -> list[Frame]:
    """One Frame per time step (time-series programs) or a single Frame.

    Channels without a time series hold their constant values at every step.
    A point's own frequency (frequency that changes over time) is used when
    it has one; otherwise the channel's.
    """
    channels = list(getattr(program, "channels", None) or [])
    if not channels:
        return []
    longest = max((len(c.time_series) for c in channels), default=0)
    if longest == 0:
        return [Frame(0, 0.0, [_command(c, c.pulse_width_us, c.amplitude_ma, c.frequency_hz)
                               for c in channels])]

    timeline = max(channels, key=lambda c: len(c.time_series)).time_series
    frames = []
    for index in range(longest):
        commands = []
        for c in channels:
            if c.time_series:
                point = c.time_series[min(index, len(c.time_series) - 1)]
                frequency = getattr(point, "frequency_hz", None)
                if frequency is None:
                    frequency = c.frequency_hz  # frequency doesn't change over time
                commands.append(_command(c, point.pulse_width_us, point.amplitude_ma, frequency))
            else:
                commands.append(_command(c, c.pulse_width_us, c.amplitude_ma, c.frequency_hz))
        frames.append(Frame(index, float(timeline[index].time_s), commands))
    return frames


def _command(channel: Any, pulse_width: Any, amplitude: Any, frequency: Any) -> ChannelCommand:
    if not (isinstance(frequency, (int, float)) and math.isfinite(frequency) and frequency > 0):
        frequency = 1.0  # only reachable for programs that failed validation
    return ChannelCommand(int(channel.number), pulse_width, amplitude, float(frequency))
