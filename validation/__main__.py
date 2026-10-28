"""Check program files against the safe ranges from the terminal.

    python -m validation samples/valid_4_channel.json samples/unsafe_amplitude.json
    python -m validation samples/*.json --ranges path/to/other_ranges.json
    python -m validation samples/matlab/ramp_2ch.mat samples/matlab/ramp_2ch.csv

Prints PASSED or FAILED for each file, with a plain-language line for every
problem. Exits with code 1 if any file fails or can't be read.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from files import IMPORT_SUFFIXES, ProgramFileError, import_time_series
from files.program import Program

from . import DEFAULT_RANGES_PATH, ValidationEngine, load_or_exit_message


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(errors="replace")  # e.g. "µs" on an old console
    except (AttributeError, ValueError):
        pass

    parser = argparse.ArgumentParser(
        prog="python -m validation",
        description="Check stimulation program files against validation/ranges.json.",
    )
    parser.add_argument("files", nargs="+", type=Path, help="Program JSON file(s) to check.")
    parser.add_argument("--ranges", type=Path, default=DEFAULT_RANGES_PATH,
                        help="Safe range limits file (default: validation/ranges.json).")
    args = parser.parse_args(argv)

    ranges, message = load_or_exit_message(args.ranges)
    if message:
        print(message)
    if ranges is None:
        return 1
    engine = ValidationEngine(ranges)
    print(f"Limits: {ranges.path}")

    all_ok = True
    for path in args.files:
        print()
        try:
            if path.suffix.lower() in IMPORT_SUFFIXES:
                program = import_time_series(path)  # MATLAB / CSV time series
            else:
                with open(path, encoding="utf-8") as handle:
                    program = Program.from_dict(json.load(handle))
        except ProgramFileError as ex:
            print(f"{path}: COULD NOT IMPORT")
            for line in str(ex).splitlines()[1:]:
                print(f"  {line}")
            all_ok = False
            continue
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as ex:
            print(f"{path}: COULD NOT READ - {ex}")
            all_ok = False
            continue

        result = engine.validate(program)
        title = f" ({program.name})" if program.name else ""
        print(f"{path}{title}: {'PASSED' if result.is_valid else 'FAILED'}")
        for problem in result.failed_parameters:
            print(f"  - {problem}")
        all_ok = all_ok and result.is_valid

    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
