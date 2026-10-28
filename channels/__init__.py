"""Multi-Channel Manager (SDS 2.2): turns validated programs into
per-channel commands and runs them on the WSS (simulated mode for now)."""

from .program_runner import (
    ALLOWED_MODES,
    ChannelCommand,
    Frame,
    ProgramRunner,
    RunRefused,
    RunState,
    build_frames,
)

__all__ = [
    "ALLOWED_MODES",
    "ChannelCommand",
    "Frame",
    "ProgramRunner",
    "RunRefused",
    "RunState",
    "build_frames",
]
