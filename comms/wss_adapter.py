"""Adapter that drives the WSS through the existing Python wrapper.

Wrapper repository: cwru-non-academic/HFI_WSS_Python_Interface, imported as
``wss_py_wrapper``. It loads the C# WSS core DLLs through pythonnet.

``simulated=True`` sets ``WssConfig.test_mode``, which is exactly what the CLI's
``--test`` flag does. The C# core then uses its built-in ``TestModeTransport``
instead of a serial port. Everything above the transport is the real code
path: framing, setup sequence, params layer and model layer. The transport
answers each command with a synthetic reply, and it writes every outgoing
frame to the wrapper's log file as ``Out: c0 ...``.

This mode still needs pythonnet, a .NET runtime and the bundled DLLs. On a
machine without those, use the ``fake`` mode (``FakeCommunicationAdapter``).
"""

from __future__ import annotations

import sys
import time
from dataclasses import replace
from pathlib import Path
from typing import Any

from .base import CommunicationAdapter, ConnectionLostError, logger


def _import_wrapper(wrapper_src: Path | None):
    """Import ``wss_py_wrapper``, optionally from a submodule checkout."""
    try:
        import wss_py_wrapper  # type: ignore

        return wss_py_wrapper
    except ModuleNotFoundError:
        if wrapper_src is not None and wrapper_src.is_dir():
            sys.path.insert(0, str(wrapper_src))
            import wss_py_wrapper  # type: ignore

            return wss_py_wrapper
        raise


class WssCommunicationAdapter(CommunicationAdapter):
    """Real adapter. Talks to the WSS hardware, or to the wrapper's test transport.

    :param config_dir: Folder with ``stimConfig.json``, ``stimParams.json`` and ``modelConfig.json``.
    :param log_path: Where the wrapper writes its C# log (raw frames go here).
    :param cs_lib_dir: Folder with the WSS DLLs (``Cs_Libraries``).
    :param simulated: Use the wrapper's built-in test transport instead of serial.
    :param serial_port: Serial device name. ``None`` means auto-detect.
    :param ready_timeout_s: How long ``connect()`` waits for the core to report Ready.
    :param wrapper_src: Optional path to ``external/wss-py-wrapper/src``.
    :param controller_factory: For unit tests only. Replaces ``StimulationController``.
    """

    def __init__(
        self,
        config_dir: Path,
        log_path: Path,
        cs_lib_dir: Path,
        simulated: bool = False,
        serial_port: str | None = None,
        tick_interval_ms: int = 10,
        max_setup_tries: int = 5,
        ready_timeout_s: float = 10.0,
        wrapper_src: Path | None = None,
        controller_factory: Any = None,
        config_factory: Any = None,
    ) -> None:
        super().__init__()
        self.mode = "simulated" if simulated else "hardware"
        self.supports_fake_disconnect = simulated
        self._ready_timeout_s = ready_timeout_s

        if controller_factory is None or config_factory is None:
            wrapper = _import_wrapper(wrapper_src)
            controller_factory = controller_factory or wrapper.StimulationController
            config_factory = config_factory or wrapper.WssConfig

        config = config_factory(
            config_path=Path(config_dir),
            log_path=Path(log_path),
            cs_lib_dir=Path(cs_lib_dir),
        )
        config = replace(
            config,
            serial_port=serial_port,
            test_mode=simulated,  # <-- the whole "simulated" switch
            tick_interval_ms=tick_interval_ms,
            max_setup_tries=max_setup_tries,
        )
        self.wss_config = config
        self._controller_factory = controller_factory
        self._controller = None

    # backend hooks -------------------------------------------------------

    def _do_connect(self) -> None:
        self.wss_config.config_path.mkdir(parents=True, exist_ok=True)
        self.wss_config.log_path.parent.mkdir(parents=True, exist_ok=True)
        self._controller = self._controller_factory(self.wss_config)
        self._controller.Initialize()

        # In the C# core, Ready() is true only in the Ready state. Setup ends
        # with StartStim, so the core soon moves to Started/Streaming. Treat
        # either state as "connected".
        deadline = time.monotonic() + self._ready_timeout_s
        while not (self._controller.Ready() or self._controller.Started()):
            if time.monotonic() > deadline:
                self._safe_shutdown()
                raise ConnectionLostError(
                    f"WSS did not become ready within {self._ready_timeout_s}s "
                    f"(see {self.wss_config.log_path})."
                )
            time.sleep(0.05)

    def _do_disconnect(self) -> None:
        self._safe_shutdown()

    def _do_start(self) -> None:
        self._ctrl().StartStimulation()

    def _do_stop(self) -> None:
        self._ctrl().StopStimulation()

    def _do_stimulate(self, channel: int, magnitude: float) -> None:
        self._ctrl().StimWithMode(f"ch{channel}", float(magnitude))

    def _do_stimulate_analog(self, channel: int, pw: int, amp: int, ipi: int) -> None:
        self._ctrl().StimulateAnalog(f"ch{channel}", int(pw), int(amp), int(ipi))

    def _set_port(self, port: str) -> None:
        self.wss_config = replace(self.wss_config, serial_port=port)

    def _is_alive(self) -> bool:
        # Not yet confirmed on the real WSS: assumes the core leaves the
        # Ready/Started states when the serial link fails.
        ctrl = self._controller
        return ctrl is not None and bool(ctrl.Ready() or ctrl.Started())

    def _on_simulated_disconnect(self) -> None:
        # The C# TestModeTransport cannot be told to drop the link from
        # Python: the wrapper never exposes the transport object. So the fake
        # disconnect happens here, at the adapter boundary. We zero the output
        # and shut the core down, exactly as the core does on a real transport
        # error, and from then on the adapter refuses commands.
        self._safe_shutdown()

    def _status_detail(self) -> str:
        if self._controller is None:
            return "controller not initialized"
        try:
            return f"ready={self._controller.Ready()} started={self._controller.Started()}"
        except Exception as ex:
            return f"status unavailable: {ex}"

    # helpers --------------------------------------------------------------

    def _ctrl(self):
        if self._controller is None:
            raise ConnectionLostError("WSS controller is not initialized.")
        return self._controller

    def _safe_shutdown(self) -> None:
        ctrl, self._controller = self._controller, None
        if ctrl is None:
            return
        for step in ("StopStimulation", "Shutdown"):
            try:
                getattr(ctrl, step)()
            except Exception as ex:
                logger.warning("[%s] %s during shutdown failed: %s", self.mode, step, ex)
