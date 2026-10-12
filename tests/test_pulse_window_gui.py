"""Checks the Test Pulse Window against its Sprint 1 "done when" list,
using the fake adapter and an off-screen Qt display (no hardware)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6.QtWidgets")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PySide6.QtWidgets import QApplication  # noqa: E402

from comms import FakeCommunicationAdapter  # noqa: E402
from ui import pulse_window as pw  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def window(app):
    w = pw.TestPulseWindow(FakeCommunicationAdapter())
    yield w
    w.close()


def test_starts_not_connected_with_pulse_disabled_and_stop_available(window):
    assert window.status_label.text() == "Not connected"
    assert not window.pulse_button.isEnabled()
    assert window.stop_button.isEnabled()
    assert "SIMULATED" in window.mode_label.text()


def test_connect_send_pulse_and_stop(window, app):
    window.connect_button.click()
    assert window.status_label.text() == "Connected"
    assert window.pulse_button.isEnabled()

    window.pulse_button.click()
    a = window.adapter
    assert a.stimulating
    assert a.channel_outputs[pw.TEST_CHANNEL]["amplitude"] == pw.TEST_AMPLITUDE
    assert "stimulate_analog" in window.log_view.toPlainText()  # the log line

    window.stop_button.click()
    assert not a.stimulating
    assert window.output_label.text() == "Off"


def test_status_follows_a_disconnect(window):
    window.connect_button.click()
    window.pulse_button.click()
    window.drop_button.click()
    assert window.status_label.text().startswith("Connection lost")
    assert not window.pulse_button.isEnabled()
    assert not window.adapter.stimulating


def test_status_follows_an_unplug_found_by_the_timer(app):
    class Unplugged(FakeCommunicationAdapter):
        alive = True

        def _is_alive(self):
            return self.alive

    adapter = Unplugged()
    w = pw.TestPulseWindow(adapter)
    w.connect_button.click()
    adapter.alive = False
    w._tick()  # what the 1-second timer does
    app.processEvents()
    assert w.status_label.text().startswith("Connection lost")
    w.close()


def test_errors_show_a_message_instead_of_crashing(window):
    window.send_test_pulse()  # not connected yet
    assert window.message_label.text().startswith("Error:")


def test_hardware_mode_lists_ports(app):
    class Hardware(FakeCommunicationAdapter):
        mode = "hardware"
        supports_fake_disconnect = False

    w = pw.TestPulseWindow(Hardware(), port_lister=lambda: ["COM3", "COM4"])
    items = [w.port_combo.itemText(i) for i in range(w.port_combo.count())]
    assert items == [pw.AUTO_DETECT, "COM3", "COM4"]
    assert not w.drop_button.isVisible()

    w.port_combo.setCurrentText("COM4")
    w.connect_button.click()
    assert w.adapter.command_log[-1].args == {"port": "COM4"}
    w.close()
