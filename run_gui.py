"""Open the Test Pulse Window.

    python run_gui.py --fake         # pure Python, works on any laptop
    python run_gui.py --simulated    # wrapper's test transport (needs .NET + DLLs)
    python run_gui.py                # mode from config/app_config.json, else hardware
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication

from comms import add_mode_arguments, create_adapter, load_app_config, resolve_mode
from ui.pulse_window import TestPulseWindow

ROOT = Path(__file__).resolve().parent


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="COSMIIC WSS Test Pulse Window")
    parser.add_argument("--app-config", type=Path, default=ROOT / "config" / "app_config.json")
    add_mode_arguments(parser)
    args = parser.parse_args(argv)

    app_config = load_app_config(args.app_config)
    mode = resolve_mode(args.comm_mode, app_config)
    try:
        adapter = create_adapter(
            mode, app_config, base_dir=ROOT,
            fake_disconnect_after_commands=args.fake_disconnect_after,
        )
    except Exception as ex:
        print(f"Could not set up {mode} mode: {str(ex).splitlines()[0]}")
        if mode != "fake":
            print("No .NET runtime or wrapper here? Try:  python run_gui.py --fake")
        return 1

    app = QApplication(sys.argv[:1])
    window = TestPulseWindow(adapter)
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
