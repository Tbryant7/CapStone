"""The Main Menu shows the live WSS status bar (SDS Screen 1) with its own
Connect button, and closes the connection safely when the window closes."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6.QtWidgets")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PySide6.QtWidgets import QApplication  # noqa: E402

from comms import FakeCommunicationAdapter  # noqa: E402
from ui.wss_status_bar import WssStatusBar  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def menu(app, tmp_path):
    from ui.main_menu import MainMenuWindow

    with patch("ui.main_menu.RECENT_PROGRAMS_FILE", tmp_path / "recent.json"):
        adapter = FakeCommunicationAdapter(channel_count=4)
        window = MainMenuWindow(adapter=adapter)
        yield window
        window.close()


def test_menu_has_the_live_status_bar(menu):
    assert isinstance(menu.statusBar(), WssStatusBar)
    assert menu.wss_status_bar.text() == (
        "WSS: Not connected | Channels: none (not connected) | SIMULATED (fake mode)"
    )


def test_connect_button_on_the_bar(menu, app):
    bar = menu.wss_status_bar
    bar.connect_button.click()
    app.processEvents()
    assert bar.state_label.text() == "WSS: Connected"
    assert bar.channels_label.text() == "Channels: 4 on WSS"
    assert bar.connect_button.text() == "Disconnect"

    bar.connect_button.click()
    assert bar.state_label.text() == "WSS: Not connected"
    assert bar.connect_button.text() == "Connect"


def test_connect_error_is_shown_not_raised(menu):
    def fail():
        raise OSError("Port COM9 is unavailable")

    menu.adapter._do_connect = fail
    menu.wss_status_bar.connect_button.click()
    assert menu.wss_status_bar.error_label.text() == "Could not connect: Port COM9 is unavailable"
    assert not menu.adapter.is_connected


def test_disconnect_is_seen_on_the_menu(menu, app):
    menu.adapter.connect()
    menu.adapter.simulate_disconnect("cable pulled")
    app.processEvents()
    assert menu.wss_status_bar.state_label.text() == "WSS: Connection lost (cable pulled)"


def test_closing_the_menu_stops_and_disconnects(app, tmp_path):
    from ui.main_menu import MainMenuWindow

    with patch("ui.main_menu.RECENT_PROGRAMS_FILE", tmp_path / "recent.json"):
        adapter = FakeCommunicationAdapter()
        window = MainMenuWindow(adapter=adapter)
        adapter.connect()
        adapter.start_stimulation()
        window.close()
    assert not adapter.is_connected
    assert not adapter.stimulating


def test_menu_without_an_adapter_still_opens(app, tmp_path):
    from ui.main_menu import MainMenuWindow

    with patch("ui.main_menu.RECENT_PROGRAMS_FILE", tmp_path / "recent.json"):
        window = MainMenuWindow()
        assert window.wss_status_bar is None
        assert "no connection set up" in window.statusBar().currentMessage()
        window.close()


def test_run_menu_accepts_the_fake_flags(tmp_path, capsys):
    import run_menu

    assert run_menu.main(["--fake", "--ranges", str(tmp_path / "missing.json")]) == 1
    assert "Cannot start" in capsys.readouterr().out
