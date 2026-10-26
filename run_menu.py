"""Open the Main Menu (Screen 1).

    python run_menu.py                                  # empty Opened Program panel
    python run_menu.py samples/unsafe_amplitude.json    # open a program straight away
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication

from files import ProgramFileManager
from validation import DEFAULT_RANGES_PATH, ValidationEngine, load_or_exit_message
from ui.main_menu import MainMenuWindow


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="COSMIIC Main Menu")
    parser.add_argument("program", nargs="?", type=Path,
                        help="Program file to open at start (e.g. samples/valid_4_channel.json).")
    parser.add_argument("--ranges", type=Path, default=DEFAULT_RANGES_PATH,
                        help="Safe range limits file (default: validation/ranges.json).")
    args = parser.parse_args(argv)

    # Never start without valid safety limits (Safe range config card).
    ranges, message = load_or_exit_message(args.ranges)
    if message:
        print(message)
    if ranges is None:
        return 1

    app = QApplication(sys.argv[:1])
    window = MainMenuWindow(ProgramFileManager(ValidationEngine(ranges)))
    window.show()
    if args.program:
        window.open_program_file(args.program)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
