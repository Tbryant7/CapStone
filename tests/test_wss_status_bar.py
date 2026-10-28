"""WSS status bar card: connection state and device channel count, updated
on every change and by a timer, always in words, with a SIMULATED label in
simulated modes. Runs off-screen with the fake adapter (no hardware)."""

from __future__ import annotations

import os
import sys
import threading
from dataclasses import dataclass
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6.QtWidgets")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PySide6.QtWidgets import QApplication  # noqa: E402

from comms import ConnectionState, FakeCommunicationAdapter, create_adapter  # noqa: E402
from comms.wss_adapter import WssCommunicationAdapter  # noqa: E402
from ui.wss_status_bar import STATE_TEXT, WssStatusBar  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def make_bar(adapter, **kw):
    kw.setdefault("port_lister", lambda: [])
    return WssStatusBar(adapter, **kw)


class Unpluggable(FakeCommunicationAdapter):
    alive = True

    def _is_alive(self):
        return self.alive


# ------------------------------------------------------------- states


def test_starts_not_connected_and_says_simulated(app):
    bar = make_bar(FakeCommunicationAdapter())
    assert bar.state_label.text() == "WSS: Not connected"
    assert bar.channels_label.text() == "Channels: none (not connected)"
    assert bar.mode_label.text() == "SIMULATED (fake mode)"
    bar.stop()


def test_connect_shows_connected_and_device_channel_count(app):
    adapter = FakeCommunicationAdapter(channel_count=6)  # not a hard-coded 4
    bar = make_bar(adapter)
    adapter.connect()
    app.processEvents()
    assert bar.state_label.text() == "WSS: Connected"
    assert bar.channels_label.text() == "Channels: 6 on WSS"
    bar.stop()


def test_channel_count_change_is_picked_up_by_the_timer(app):
    adapter = FakeCommunicationAdapter(channel_count=4)
    bar = make_bar(adapter)
    adapter.connect()
    adapter.reported_channels = 2
    bar._tick()  # what the 2-second timer does
    assert bar.channels_label.text() == "Channels: 2 on WSS"
    bar.stop()


def test_unknown_channel_count_is_said_in_words(app):
    adapter = FakeCommunicationAdapter()
    adapter._channel_count = lambda: None
    bar = make_bar(adapter)
    adapter.connect()
    app.processEvents()
    assert bar.channels_label.text() == "Channels: unknown"
    bar.stop()


def test_disconnect_updates_immediately(app):
    adapter = FakeCommunicationAdapter()
    bar = make_bar(adapter)
    adapter.connect()
    adapter.disconnect()
    app.processEvents()
    assert bar.state_label.text() == "WSS: Not connected"
    bar.stop()


def test_lost_connection_shows_reason(app):
    adapter = FakeCommunicationAdapter()
    bar = make_bar(adapter)
    adapter.connect()
    adapter.simulate_disconnect("cable pulled")
    app.processEvents()
    assert bar.state_label.text() == "WSS: Connection lost (cable pulled)"
    assert bar.channels_label.text() == "Channels: none (not connected)"
    bar.stop()


def test_unplug_is_noticed_by_the_timer_within_one_tick(app):
    adapter = Unpluggable()
    bar = make_bar(adapter, check_interval_ms=50)
    adapter.connect()
    app.processEvents()
    assert bar.state_label.text() == "WSS: Connected"

    adapter.alive = False  # WSS unplugged; nobody calls the adapter
    bar._tick()
    app.processEvents()
    assert bar.state_label.text().startswith("WSS: Connection lost")
    bar.stop()


def test_timer_is_running_with_a_few_second_interval(app):
    bar = make_bar(FakeCommunicationAdapter())
    assert bar._timer.isActive()
    assert bar._timer.interval() <= 3000
    bar.stop()
    assert not bar._timer.isActive()


def test_update_from_another_thread_lands_on_the_gui_thread(app):
    adapter = FakeCommunicationAdapter()
    bar = make_bar(adapter)
    adapter.connect()
    worker = threading.Thread(target=adapter.simulate_disconnect, args=("background drop",))
    worker.start()
    worker.join()
    app.processEvents()
    assert bar.state_label.text() == "WSS: Connection lost (background drop)"
    bar.stop()


@pytest.mark.parametrize("state", list(ConnectionState))
def test_every_state_has_text_not_just_color(state):
    assert STATE_TEXT[state].startswith("WSS: ")
    assert len(STATE_TEXT[state]) > len("WSS: ")


# ------------------------------------------------------------ hardware


class _HardwareFake(FakeCommunicationAdapter):
    mode = "hardware"
    supports_fake_disconnect = False


def test_hardware_mode_has_no_simulated_label(app):
    bar = make_bar(_HardwareFake())
    assert "SIMULATED" not in bar.text()
    assert bar.mode_label.text() == "Hardware"
    bar.stop()


def test_hardware_mode_says_when_a_serial_device_is_plugged_in(app):
    ports: list[str] = []
    bar = make_bar(_HardwareFake(), port_lister=lambda: list(ports))
    assert bar.state_label.text() == "WSS: Not connected (no serial device found)"

    ports.append("COM3")  # plugged in
    bar._tick()
    assert bar.state_label.text() == "WSS: Not connected (serial device found: COM3)"
    bar.stop()


def test_port_lister_errors_do_not_crash(app):
    def broken():
        raise OSError("no access")

    bar = make_bar(_HardwareFake(), port_lister=broken)
    assert bar.state_label.text() == "WSS: Not connected (no serial device found)"
    bar.stop()


# --------------------------------------------- adapter channel counting


def test_fake_channel_count_from_config(tmp_path):
    adapter = create_adapter(
        "fake", {"communication": {"log_dir": str(tmp_path), "fake_channel_count": 3}}
    )
    adapter.connect()
    assert adapter.channel_count() == 3


def test_channel_count_is_none_when_not_connected():
    assert FakeCommunicationAdapter().channel_count() is None


def test_channel_count_errors_become_unknown():
    adapter = FakeCommunicationAdapter()

    def boom():
        raise RuntimeError("device busy")

    adapter._channel_count = boom
    adapter.connect()
    assert adapter.channel_count() is None


def test_channel_count_is_not_written_to_the_command_log():
    adapter = FakeCommunicationAdapter()
    adapter.connect()
    before = len(adapter.command_log)
    adapter.channel_count()
    assert len(adapter.command_log) == before


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
    channels = 3

    def __init__(self, cfg):
        self.asked = []

    def Initialize(self):
        pass

    def Ready(self):
        return True

    def Started(self):
        return False

    def IsFingerValid(self, finger):
        self.asked.append(finger)
        return int(finger[2:]) <= self.channels

    def StopStimulation(self):
        pass

    def Shutdown(self):
        pass


def test_real_adapter_counts_channels_the_device_says_are_valid(tmp_path):
    made = []

    def factory(cfg):
        made.append(_Ctrl(cfg))
        return made[-1]

    adapter = WssCommunicationAdapter(
        config_dir=tmp_path, log_path=tmp_path / "w.log", cs_lib_dir=tmp_path,
        controller_factory=factory, config_factory=_Cfg,
    )
    adapter.connect()
    assert adapter.channel_count() == 3
    assert made[-1].asked == ["ch1", "ch2", "ch3", "ch4"]


def test_real_adapter_channel_probe_has_an_upper_bound(tmp_path):
    class Endless(_Ctrl):
        def IsFingerValid(self, finger):
            return True

    adapter = WssCommunicationAdapter(
        config_dir=tmp_path, log_path=tmp_path / "w.log", cs_lib_dir=tmp_path,
        controller_factory=Endless, config_factory=_Cfg,
    )
    adapter.connect()
    assert adapter.channel_count() == 64


# ---------------------------------------------------- in the window


def test_test_pulse_window_has_the_status_bar(app):
    from ui.pulse_window import TestPulseWindow

    window = TestPulseWindow(FakeCommunicationAdapter(channel_count=5))
    assert window.statusBar() is window.wss_status_bar
    window.connect_button.click()
    app.processEvents()
    assert window.wss_status_bar.text() == (
        "WSS: Connected | Channels: 5 on WSS | SIMULATED (fake mode)"
    )
    window.close()
