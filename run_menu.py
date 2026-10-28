"""Open the Main Menu (Screen 1).

    python run_menu.py                                  # mode from config/app_config.json
    python run_menu.py --fake --fake-channels 4         # fake WSS, shown in the status bar
    python run_menu.py samples/unsafe_amplitude.json    # open a program straight away
    python run_menu.py --comm-mode hardware             # real WSS (lab computer)
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication

from comms import add_mode_arguments, create_adapter, load_app_config, resolve_mode
from files import ProgramFileManager
from validation import DEFAULT_RANGES_PATH, ValidationEngine, load_or_exit_message
from ui.main_menu import MainMenuWindow

ROOT = Path(__file__).resolve().parent


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="COSMIIC Main Menu")
    parser.add_argument("program", nargs="?", type=Path,
                        help="Program file to open at start (e.g. samples/valid_4_channel.json).")
    parser.add_argument("--ranges", type=Path, default=DEFAULT_RANGES_PATH,
                        help="Safe range limits file (default: validation/ranges.json).")
    parser.add_argument("--app-config", type=Path, default=ROOT / "config" / "app_config.json")
    add_mode_arguments(parser)
    args = parser.parse_args(argv)

    # Never start without valid safety limits (Safe range config card).
    ranges, message = load_or_exit_message(args.ranges)
    if message:
        print(message)
    if ranges is None:
        return 1

    app_config = load_app_config(args.app_config)
    mode = resolve_mode(args.comm_mode, app_config)
    try:
        adapter = create_adapter(
            mode, app_config, base_dir=ROOT,
            fake_disconnect_after_commands=args.fake_disconnect_after,
            fake_channel_count=args.fake_channels,
        )
    except Exception as ex:
        print(f"Could not set up {mode} mode: {str(ex).splitlines()[0]}")
        if mode != "fake":
            print("No .NET runtime or wrapper here? Try:  python run_menu.py --fake")
        return 1

    app = QApplication(sys.argv[:1])
    window = MainMenuWindow(ProgramFileManager(ValidationEngine(ranges)), adapter)
    window.show()
    if args.program:
        window.open_program_file(args.program)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
