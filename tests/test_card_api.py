"""Tests for the method names on the Sprint 1 CommunicationAdapter card:
connect(port), send_test_pulse(...), stop() and is_connected, plus the
connection check the Test Pulse Window uses to notice an unplugged WSS.
None of them need hardware or .NET."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from comms import ConnectionLostError, ConnectionState, FakeCommunicationAdapter  # noqa: E402
from comms.wss_adapter import WssCommunicationAdapter  # noqa: E402


def test_connect_with_port_is_logged():
    a = FakeCommunicationAdapter()
    a.connect("COM3")
    assert a.is_connected
    assert (a.command_log[-1].command, a.command_log[-1].args) == ("connect", {"port": "COM3"})


def test_send_test_pulse_starts_stimulation_once_and_stop_halts_it():
    a = FakeCommunicationAdapter()
    a.connect()
    a.send_test_pulse(1, pulse_width=50, amplitude=1, ipi=50)
    a.send_test_pulse(1, pulse_width=50, amplitude=1, ipi=50)
    assert a.stimulating
    assert a.channel_outputs[1] == {"pulse_width": 50, "amplitude": 1, "ipi": 50}

    a.stop()
    assert not a.stimulating
    assert a.channel_outputs == {}
    assert [r.command for r in a.command_log] == [
        "connect", "start_stimulation", "stimulate_analog", "stimulate_analog", "stop_stimulation",
    ]


def test_send_test_pulse_when_not_connected_raises_clear_error():
    a = FakeCommunicationAdapter()
    with pytest.raises(ConnectionLostError, match="not connected"):
        a.send_test_pulse(1, 50, 1)


def test_stop_never_raises_when_not_connected():
    FakeCommunicationAdapter().stop()


def test_check_connection_marks_lost_when_backend_is_gone():
    class Unplugged(FakeCommunicationAdapter):
        alive = True

        def _is_alive(self):
            return self.alive

    a = Unplugged()
    seen = []
    a.add_status_listener(lambda s: seen.append(s.state))
    a.connect()
    a.send_test_pulse(1, 50, 1)
    assert a.check_connection() is True

    a.alive = False
    assert a.check_connection() is False
    assert a.status().state is ConnectionState.LOST
    assert not a.stimulating
    assert seen[-1] is ConnectionState.LOST
    assert a.command_log[-1].outcome.startswith("lost:")


def test_check_connection_treats_exceptions_as_lost():
    class Broken(FakeCommunicationAdapter):
        def _is_alive(self):
            raise OSError("port vanished")

    a = Broken()
    a.connect()
    assert a.check_connection() is False
    assert "port vanished" in a.command_log[-1].outcome


# -- real adapter, with a stand-in controller and config (no wrapper needed) --


@dataclass(frozen=True)
class _Cfg:
    config_path: Path
    log_path: Path
    cs_lib_dir: Path
    serial_port: str | None = None
    test_mode: bool = False
    tick_interval_ms: int = 10
    max_setup_tries: int = 5


class _Ctrl:
    def __init__(self, cfg):
        self.cfg = cfg
        self.ready = True

    def Initialize(self):
        pass

    def Ready(self):
        return self.ready

    def Started(self):
        return False

    def StopStimulation(self):
        pass

    def Shutdown(self):
        pass


def test_wss_connect_port_reaches_wrapper_config_and_unplug_is_detected(tmp_path):
    made = []

    def factory(cfg):
        made.append(_Ctrl(cfg))
        return made[-1]

    a = WssCommunicationAdapter(
        config_dir=tmp_path, log_path=tmp_path / "w.log", cs_lib_dir=tmp_path,
        controller_factory=factory, config_factory=_Cfg,
    )
    a.connect("COM7")
    assert made[-1].cfg.serial_port == "COM7"
    assert a.check_connection() is True

    made[-1].ready = False  # core left Ready/Started, as after an unplug
    assert a.check_connection() is False
    assert a.status().state is ConnectionState.LOST

 def test_wrong_port_shows_clear_error(tmp_path):
    class FailingController(_Ctrl):
        def Initialize(self):
            raise OSError("Port COM7 is unavailable")

    adapter = WssCommunicationAdapter(
        config_dir=tmp_path,
        log_path+tmp_path / "w.log",
        cs_lib_dir=tmp_path,
        controller_factory=FailingController,
        config_factory=_Cfg,
    )

    with pytest.raises(OSError, match= "Port COM99 is unavailable"):
        adapter.connect("COM99")

    assert not adapter.is_connected
    assert.adapter.command_log[-1].commant == "connect"
    assert "error:" in adapter.command_log[-1].outcome
 
    

