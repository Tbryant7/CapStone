"""Program data classes: what a stimulation program looks like in code.

Shared by ProgramFileManager (save/load), the ValidationEngine and the
editors. Values are allowed to be missing (``None``) so a half-filled or
damaged program can still be represented and the ValidationEngine can say
exactly what is missing, instead of the app crashing.

Units are fixed by the field names and match the WSS wrapper:
pulse width in microseconds, amplitude in milliamps, frequency in hertz,
time step in milliseconds.

JSON shape (``to_dict`` / ``from_dict``)::

    {
      "format_version": 1,
      "name": "Wrist extension",
      "description": "One channel, gentle test",
      "time_step_ms": 50,
      "channels": [
        {"channel": 1, "pulse_width_us": 50, "amplitude_ma": 1.0, "frequency_hz": 20}
      ]
    }
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

FORMAT_VERSION = 1


@dataclass
class Channel:
    number: Any = None
    pulse_width_us: Any = None
    amplitude_ma: Any = None
    frequency_hz: Any = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "channel": self.number,
            "pulse_width_us": self.pulse_width_us,
            "amplitude_ma": self.amplitude_ma,
            "frequency_hz": self.frequency_hz,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Channel":
        return cls(
            number=data.get("channel"),
            pulse_width_us=data.get("pulse_width_us"),
            amplitude_ma=data.get("amplitude_ma"),
            frequency_hz=data.get("frequency_hz"),
        )


@dataclass
class Program:
    name: str = ""
    description: str = ""
    time_step_ms: Any = None
    channels: list[Channel] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "format_version": FORMAT_VERSION,
            "name": self.name,
            "description": self.description,
            "time_step_ms": self.time_step_ms,
            "channels": [ch.to_dict() for ch in self.channels],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Program":
        """Build a Program from parsed JSON.

        This only converts shapes. It does not judge whether values are safe
        or present; that is the ValidationEngine's job. It raises
        ``ValueError`` only when the overall structure is unusable (not an
        object, or "channels" is not a list of objects).
        """
        if not isinstance(data, dict):
            raise ValueError("A program must be a JSON object.")
        raw_channels = data.get("channels", [])
        if raw_channels is None:
            raw_channels = []
        if not isinstance(raw_channels, list) or not all(isinstance(c, dict) for c in raw_channels):
            raise ValueError('"channels" must be a list of channel objects.')
        return cls(
            name=str(data.get("name") or ""),
            description=str(data.get("description") or ""),
            time_step_ms=data.get("time_step_ms"),
            channels=[Channel.from_dict(c) for c in raw_channels],
        )
