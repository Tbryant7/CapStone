"""Tests for the Communication Adapter. None of them need hardware or .NET."""

from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from communication import (  # noqa: E402
    ConnectionLostError,
    ConnectionState,
    FakeCommunicationAdapter,
    create_adapter,
    resolve_mode,
)
from communication.wss_adapter import WssCommunicationAdapter  # noqa: E402

WRAPPER_SRC = ROOT / "external" / "wss-py-wrapper" / "src"


# ------------------------------------------------------------ one setting


@pytest.mark.parametrize(
    "cli, cfg, expected",
    [
        (None, {}, "hardware"),
        (None, {"communication": {"mode": "fake"}}, "fake"),
        (None, {"communication": {"mode": "SIMULATED"}}, "simulated"),
        ("fake", {"communication": {"mode": "hardware"}}, "fake"),  # flag beats config
    ],
)
def test_resolve_mode(cli, cfg, expected):
    assert resolve_mode(cli, cfg) == expected


def test_resolve_mode_rejects_typos():
    with pytest.raises(ValueError):
        resolve_mode("simulate", {})


def test_fake_mode_from_config_builds_fake_adapter(tmp_path):
    adapter = create_adapter("fake", {"communication": {"log_dir": str(tmp_path)}})
    assert isinstance(adapter, FakeCommunicationAdapter)


# ------------------------------------------------- logs every command


def test_every_command_is_logged_with_args_and_outcome():
    a = FakeCommunicationAdapter()
    a.connect()
    a.start_stimulation()
    a.stimulate(2, 0.5)
    a.stimulate_analog(1, 200, 3, 25)
    a.stop_stimulation()
    a.disconnect()

    log = [(r.command, r.args, r.outcome) for r in a.command_log]
    assert log == [
        ("connect", {}, "ok"),
        ("start_stimulation", {}, "ok"),
        ("stimulate", {"channel": 2, "magnitude": 0.5}, "ok"),
        ("stimulate_analog", {"channel": 1, "pulse_width": 200, "amplitude": 3, "ipi": 25}, "ok"),
        ("stop_stimulation", {}, "ok"),
        ("stop_stimulation", {"reason": "disconnect"}, "ok"),  # safety stop before closing
        ("disconnect", {}, "ok"),
    ]


def test_rejected_commands_are_logged_too():
    a = FakeCommunicationAdapter()
    with pytest.raises(ConnectionLostError):
        a.stimulate(1, 0.2)  # never connected
    assert a.command_log[-1].outcome == "rejected: not connected"


def test_commands_reach_the_log_file(tmp_path):
    adapter = create_adapter("fake", {"communication": {"log_dir": str(tmp_path)}})
    adapter.connect()
    adapter.stimulate(3, 0.75)
    text = "".join(p.read_text() for p in tmp_path.glob("commands_*.log"))
    assert "stimulate(channel=3 magnitude=0.75) -> ok" in text


def test_fake_tracks_channel_outputs():
    a = FakeCommunicationAdapter()
    a.connect()
    a.stimulate(2, 0.4)
    assert a.channel_outputs == {2: {"magnitude": 0.4}}
    a.stop_stimulation()
    assert a.channel_outputs == {}


def test_no_hardcoded_channel_limit_but_rejects_nonsense():
    a = FakeCommunicationAdapter()
    a.connect()
    a.stimulate(12, 0.1)  # beyond 4 channels is the validator's call, not the adapter's
    for bad in (0, -1, "2", True):
        with pytest.raises(ValueError):
            a.stimulate(bad, 0.1)


# ------------------------------------------------------ fake disconnect


def test_simulate_disconnect_blocks_commands_and_notifies():
    a = FakeCommunicationAdapter()
    seen = []
    a.add_status_listener(seen.append)
    a.connect()
    a.start_stimulation()
    a.stimulate(1, 0.3)

    a.simulate_disconnect("cable yanked")

    assert a.status().state is ConnectionState.LOST
    assert a.status().stimulating is False
    assert a.channel_outputs == {}
    assert seen[-1].state is ConnectionState.LOST and seen[-1].detail == "cable yanked"
    with pytest.raises(ConnectionLostError, match="connection lost"):
        a.stimulate(1, 0.3)
    assert a.command_log[-1].outcome == "rejected: connection lost"


def test_stop_never_raises_even_after_disconnect():
    a = FakeCommunicationAdapter()
    a.connect()
    a.simulate_disconnect()
    a.stop_stimulation()  # must not raise: stop is the safety path
    assert a.command_log[-1].command == "stop_stimulation"


def test_reconnect_after_disconnect():
    a = FakeCommunicationAdapter()
    a.connect()
    a.simulate_disconnect()
    a.connect()
    a.stimulate(1, 0.2)
    assert a.is_connected


def test_disconnect_after_n_commands_is_repeatable():
    a = FakeCommunicationAdapter(disconnect_after_commands=3)
    a.connect()
    a.start_stimulation()
    a.stimulate(1, 0.1)
    a.stimulate(1, 0.2)  # 3rd command succeeds, then the link drops
    with pytest.raises(ConnectionLostError):
        a.stimulate(1, 0.3)
    outcomes = [r.outcome for r in a.command_log if r.command == "stimulate"]
    assert outcomes == ["ok", "ok", "rejected: connection lost"]


def test_disconnect_after_seconds():
    a = FakeCommunicationAdapter(disconnect_after_seconds=0.1)
    a.connect()
    time.sleep(0.3)
    assert a.status().state is ConnectionState.LOST


# --------------------------------------------- wrapper "simulated" mode


class RecordingController:
    """Stands in for wss_py_wrapper.StimulationController."""

    instances: list["RecordingController"] = []

    def __init__(self, config):
        self.config = config
        self.calls = []
        self.ready = False
        RecordingController.instances.append(self)

    def Initialize(self):
        self.calls.append("Initialize")
        self.ready = True

    def Ready(self):
        return self.ready

    def Started(self):
        return False

    def StartStimulation(self):
        self.calls.append("StartStimulation")

    def StopStimulation(self):
        self.calls.append("StopStimulation")

    def StimWithMode(self, finger, magnitude):
        self.calls.append(("StimWithMode", finger, magnitude))

    def StimulateAnalog(self, finger, pw, amp, ipi):
        self.calls.append(("StimulateAnalog", finger, pw, amp, ipi))

    def Shutdown(self):
        self.calls.append("Shutdown")


def _wrapper():
    if not WRAPPER_SRC.is_dir():
        pytest.skip("wrapper submodule not checked out at external/wss-py-wrapper")
    sys.path.insert(0, str(WRAPPER_SRC))
    import wss_py_wrapper

    return wss_py_wrapper


def _wss_adapter(tmp_path, simulated, **kw):
    w = _wrapper()
    return WssCommunicationAdapter(
        config_dir=tmp_path / "Config", log_path=tmp_path / "wss.log",
        cs_lib_dir=tmp_path / "Cs_Libraries", simulated=simulated,
        controller_factory=RecordingController, config_factory=w.WssConfig, **kw,
    )


def test_simulated_flag_turns_on_wrapper_test_mode(tmp_path):
    assert _wss_adapter(tmp_path, simulated=True).wss_config.test_mode is True
    assert _wss_adapter(tmp_path, simulated=False).wss_config.test_mode is False


def test_real_wrapper_picks_test_transport_when_simulated(tmp_path):
    """Use the real StimulationController with dummy .NET types and check
    that test_mode makes it build TestModeTransport instead of a serial port."""
    w = _wrapper()
    for simulated, expected in ((True, "TestModeTransport"), (False, "SerialPortTransport")):
        cfg = _wss_adapter(tmp_path, simulated).wss_config
        ctrl = w.StimulationController(cfg)
        ctrl._net_types = {
            "TestModeTransport": lambda: "TestModeTransport",
            "SerialPortTransport": lambda *a: "SerialPortTransport",
        }
        assert ctrl._create_transport() == expected


def test_wss_adapter_translates_and_logs(tmp_path):
    a = _wss_adapter(tmp_path, simulated=True)
    a.connect()
    a.start_stimulation()
    a.stimulate(2, 0.5)
    a.stimulate_analog(1, 200, 3, 25)
    ctrl = RecordingController.instances[-1]
    assert ctrl.calls == [
        "Initialize", "StartStimulation",
        ("StimWithMode", "ch2", 0.5), ("StimulateAnalog", "ch1", 200, 3, 25),
    ]
    assert [r.command for r in a.command_log] == [
        "connect", "start_stimulation", "stimulate", "stimulate_analog",
    ]


def test_wss_simulated_fake_disconnect_shuts_core_down(tmp_path):
    a = _wss_adapter(tmp_path, simulated=True)
    a.connect()
    ctrl = RecordingController.instances[-1]
    a.simulate_disconnect()
    assert ctrl.calls[-2:] == ["StopStimulation", "Shutdown"]
    with pytest.raises(ConnectionLostError):
        a.stimulate(1, 0.2)


def test_fake_disconnect_refused_on_real_hardware(tmp_path):
    a = _wss_adapter(tmp_path, simulated=False)
    a.connect()
    with pytest.raises(RuntimeError, match="not allowed"):
        a.simulate_disconnect()
    assert a.is_connected


def test_connect_times_out_if_core_never_ready(tmp_path):
    class NeverReady(RecordingController):
        def Initialize(self):
            self.calls.append("Initialize")

    w = _wrapper()
    a = WssCommunicationAdapter(
        config_dir=tmp_path, log_path=tmp_path / "w.log", cs_lib_dir=tmp_path,
        simulated=True, ready_timeout_s=0.2,
        controller_factory=NeverReady, config_factory=w.WssConfig,
    )
    with pytest.raises(ConnectionLostError, match="did not become ready"):
        a.connect()
    assert "Shutdown" in RecordingController.instances[-1].calls
