"""Pick an adapter from a single setting.

Order of precedence (first one set wins):

1. Command-line flag: ``--comm-mode simulated``. ``--simulated`` and ``--fake``
   are shortcuts.
2. Config file: ``"communication": {"mode": "simulated"}`` in ``app_config.json``.
3. Default: ``hardware``.

Modes
-----
hardware   Real WSS over serial, through the wrapper.
simulated  The wrapper's own test transport (C# TestModeTransport). Runs the
           real C# stack without hardware. Needs .NET and the DLLs.
fake       FakeCommunicationAdapter, pure Python. Runs anywhere.
"""

from __future__ import annotations

import argparse
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from .base import CommunicationAdapter
from .fake_adapter import FakeCommunicationAdapter

MODES = ("hardware", "simulated", "fake")
DEFAULT_MODE = "hardware"


def add_mode_arguments(parser: argparse.ArgumentParser) -> None:
    """Add ``--comm-mode`` and its shortcuts to an existing argparse parser."""
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--comm-mode", choices=MODES, dest="comm_mode",
                       help="How to talk to the WSS (default: from config, else hardware).")
    group.add_argument("--simulated", dest="comm_mode", action="store_const", const="simulated",
                       help="Shortcut for --comm-mode simulated (wrapper test transport).")
    group.add_argument("--fake", dest="comm_mode", action="store_const", const="fake",
                       help="Shortcut for --comm-mode fake (pure Python, no .NET needed).")
    parser.add_argument("--fake-disconnect-after", type=int, metavar="N",
                        help="Fake mode: drop the connection after N commands.")


def load_app_config(path: Path | None) -> dict[str, Any]:
    if path is None or not Path(path).is_file():
        return {}
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def resolve_mode(cli_mode: str | None, app_config: dict[str, Any]) -> str:
    mode = cli_mode or app_config.get("communication", {}).get("mode") or DEFAULT_MODE
    mode = str(mode).lower()
    if mode not in MODES:
        raise ValueError(f"Unknown communication mode '{mode}'. Use one of: {', '.join(MODES)}.")
    return mode


def create_adapter(
    mode: str,
    app_config: dict[str, Any] | None = None,
    base_dir: Path | None = None,
    **overrides: Any,
) -> CommunicationAdapter:
    """Build the adapter for ``mode``.

    ``app_config["communication"]`` can hold ``config_dir``, ``cs_lib_dir``,
    ``wrapper_src``, ``serial_port``, ``log_dir`` and
    ``fake_disconnect_after_commands``. Relative paths are resolved against
    ``base_dir``. Keyword ``overrides`` win over the config.
    """
    comm = dict((app_config or {}).get("communication", {}))
    comm.update({k: v for k, v in overrides.items() if v is not None})
    base = Path(base_dir or Path.cwd())

    def path_of(key: str, default: str) -> Path:
        value = Path(comm.get(key, default)).expanduser()
        return value if value.is_absolute() else (base / value).resolve()

    log_dir = path_of("log_dir", "logs")
    configure_command_log(log_dir / f"commands_{datetime.now():%Y%m%d_%H%M%S}.log")

    if mode == "fake":
        return FakeCommunicationAdapter(
            disconnect_after_commands=comm.get("fake_disconnect_after_commands"),
            disconnect_after_seconds=comm.get("fake_disconnect_after_seconds"),
        )

    from .wss_adapter import WssCommunicationAdapter  # imports pythonnet lazily

    return WssCommunicationAdapter(
        config_dir=path_of("config_dir", "Config"),
        log_path=log_dir / f"wss_{datetime.now():%Y%m%d_%H%M%S}.log",
        cs_lib_dir=path_of("cs_lib_dir", "external/wss-py-wrapper/Cs_Libraries"),
        wrapper_src=path_of("wrapper_src", "external/wss-py-wrapper/src"),
        simulated=(mode == "simulated"),
        serial_port=comm.get("serial_port"),
    )


def configure_command_log(path: Path, echo: bool = True) -> None:
    """Send adapter command logs to ``path`` and, if ``echo``, to the console.

    Calling it again switches to the new file (one file per adapter session).
    """
    log = logging.getLogger("wss_comm")
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(message)s")
    for handler in list(log.handlers):
        if getattr(handler, "_wss_owned", False):
            log.removeHandler(handler)
            handler.close()
    path.parent.mkdir(parents=True, exist_ok=True)
    handlers: list[logging.Handler] = [logging.FileHandler(path, encoding="utf-8")]
    if echo:
        handlers.append(logging.StreamHandler())
    for handler in handlers:
        handler.setFormatter(fmt)
        handler._wss_owned = True  # type: ignore[attr-defined]
        log.addHandler(handler)
    log.setLevel(logging.INFO)
    log.propagate = False
    log.info("Command log: %s", path)
