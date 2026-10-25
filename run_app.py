"""App entry point (console version until the GUI exists).

    python run_app.py --fake                     # pure Python, works anywhere
    python run_app.py --simulated                # wrapper's test transport (needs .NET + DLLs)
    python run_app.py                            # mode from config/app_config.json, else hardware
    python run_app.py --fake --fake-disconnect-after 3

The GUI should call the same three functions: ``load_app_config``,
``resolve_mode`` and ``create_adapter``.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from validation import DEFAULT_RANGES_PATH, load_or_exit_message
from comms import (
    ConnectionLostError,
    add_mode_arguments,
    create_adapter,
    load_app_config,
    resolve_mode,
)

ROOT = Path(__file__).resolve().parent

HELP = """Commands:
  start                         start stimulation
  stop                          stop stimulation (always allowed)
  stim <ch> <0..1>              normalized stimulation on channel <ch>
  analog <ch> <pw> <amp> <ipi>  explicit pulse width / amplitude / IPI
  status                        show connection + stimulation state
  log                           show every command received so far
  drop                          simulate a disconnect (simulated/fake modes only)
  reconnect                     connect again after a drop
  quit"""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="COSMIIC WSS app")
    parser.add_argument("--app-config", type=Path, default=ROOT / "config" / "app_config.json")
    parser.add_argument("--ranges", type=Path, default=DEFAULT_RANGES_PATH,
                        help="Safe range limits file (default: validation/ranges.json).")
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
    adapter = create_adapter(
        mode, app_config, base_dir=ROOT,
        fake_disconnect_after_commands=args.fake_disconnect_after,
    )
    adapter.add_status_listener(
        lambda s: print(f"  [status] {s.state.value}, stimulating={s.stimulating} {s.detail}")
    )

    print(f"Communication mode: {mode.upper()}")
    try:
        adapter.connect()
    except Exception as ex:
        print(f"Could not connect in {mode} mode: {str(ex).splitlines()[0]}")
        if mode != "fake":
            print("No .NET runtime or WSS here? Try:  python run_app.py --fake")
        return 1
    print(HELP)
    try:
        while True:
            try:
                parts = input("> ").split()
            except EOFError:
                break
            if not parts:
                continue
            cmd, rest = parts[0].lower(), parts[1:]
            try:
                if cmd in ("quit", "exit"):
                    break
                elif cmd == "start":
                    adapter.start_stimulation()
                elif cmd == "stop":
                    adapter.stop_stimulation()
                elif cmd == "stim":
                    adapter.stimulate(int(rest[0]), float(rest[1]))
                elif cmd == "analog":
                    adapter.stimulate_analog(*(int(x) for x in rest[:4]))
                elif cmd == "status":
                    print(f"  {adapter.status()}")
                elif cmd == "log":
                    for record in adapter.command_log:
                        print(f"  {record.timestamp:%H:%M:%S.%f}"[:-3], record)
                elif cmd == "drop":
                    adapter.simulate_disconnect("dropped from console")
                elif cmd == "reconnect":
                    adapter.connect()
                else:
                    print(HELP)
            except ConnectionLostError as ex:
                print(f"  !! CONNECTION LOST: {ex} Stimulation halted. Type 'reconnect'.")
            except (ValueError, IndexError, RuntimeError) as ex:
                print(f"  error: {ex}")
    finally:
        adapter.disconnect()
    return 0


if __name__ == "__main__":
    sys.exit(main())
