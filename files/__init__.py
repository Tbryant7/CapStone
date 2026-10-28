"""Program files (SDS 2.2): ProgramFileManager JSON save/load and MATLAB/CSV import."""

from .matlab_import import IMPORT_SUFFIXES, import_time_series
from .program import Channel, Program, TimeSeriesPoint
from .program_file_manager import (
    OpenedProgram,
    ProgramFileError,
    ProgramFileManager,
    ProgramValidationError,
)

__all__ = [
    "Channel",
    "IMPORT_SUFFIXES",
    "OpenedProgram",
    "Program",
    "ProgramFileError",
    "ProgramFileManager",
    "ProgramValidationError",
    "TimeSeriesPoint",
    "import_time_series",
]
