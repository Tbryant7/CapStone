"""Run / Execute (SDS Screen 4, Figure 3.3; SRS REQ-17 - REQ-20, §5.2):
only validated programs run, only on the fake/simulated WSS for now, STOP
always works, a lost connection ends the run, and the screen says so in
words."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from channels import ProgramRunner, RunRefused, RunState, build_frames  # noqa: E402
from comms import FakeCommunicationAdapter  # noqa: E402
from files import Channel, Program, ProgramFileManager, TimeSeriesPoint  # noqa: E402
from validation import RangeTable, ValidationEngine  # noqa: E402

SAMPLES = ROOT / "samples"

TEST_RANGES = RangeTable.from_dict({
    "source": "test limits", "confirmed": True,
    "parameters": {
        "pulse_width": {"label": "pulse width", "unit": "µs", "min": 20, "max": 100},
        "amplitude": {"label": "amplitude", "unit": "mA", "min": 0, "max": 3},
        "frequency": {"label": "frequency", "unit": "Hz", "min": 1, "max": 50},
        "time_step": {"label": "time step", "unit": "ms", "min": 10, "max": 1000},
    },
})


def opened(path):
    return ProgramFileManager(ValidationEngine(TEST_RANGES)).open(SAMPLES / path)


def connected(**kw):
    adapter = FakeCommunicationAdapter(**kw)
    adapter.connect()
    return adapter


def series_program(n=5):
    points = [TimeSeriesPoint(k * 0.01, 50, k * 0.5) for k in range(n)]
    return Program("ts", "", 10, [Channel(1, 50, 0, 20, points), Channel(2, 40, 1, 25)])


# ------------------------------------------------------------------ frames


def test_constant_program_is_one_frame():
    frames = build_frames(opened("valid_4_channel.json").program)
    assert len(frames) == 1
    assert [c.channel for c in frames[0].commands] == [1, 2, 3, 4]
    assert frames[0].commands[1].ipi_ms == 40  # 25 Hz


def test_time_series_frames_and_constant_channels_hold_their_values():
    frames = build_frames(series_program())
    assert len(frames) == 5
    assert frames[3].time_s == pytest.approx(0.03)
    assert frames[3].commands[0].amplitude_ma == 1.5
    assert frames[3].commands[1].amplitude_ma == 1  # constant channel 2 holds


# ------------------------------------------------------------------ runner


def test_time_series_runs_to_complete_and_stops_output():
    o = opened("matlab/ramp_2ch.mat")
    adapter = connected()
    runner = ProgramRunner(adapter, o.program, o.validation)
    runner.start()
    assert runner.state is RunState.RUNNING and adapter.stimulating
    while runner.step():
        pass
    assert runner.state is RunState.COMPLETE
    assert runner.position == 201
    assert not adapter.stimulating
    sent = [r for r in adapter.command_log if r.command == "stimulate_analog"]
    assert len(sent) == 201 * 2
    assert sent[-2].args["amplitude"] == pytest.approx(2.5)


def test_constant_program_holds_until_stop():
    o = opened("valid_4_channel.json")
    adapter = connected()
    runner = ProgramRunner(adapter, o.program, o.validation)
    runner.start()
    for _ in range(5):
        assert runner.step()
    assert adapter.channel_outputs[4] == {"pulse_width": 80, "amplitude": 2, "ipi": 33}
    runner.stop()
    assert runner.state is RunState.STOPPED and runner.detail == "Stopped by user."
    assert not adapter.stimulating


def test_failed_validation_cannot_run():
    o = opened("unsafe_amplitude.json")
    adapter = connected()
    runner = ProgramRunner(adapter, o.program, o.validation)
    assert "failed validation" in runner.why_not_runnable()
    with pytest.raises(RunRefused, match="failed validation"):
        runner.start()
    assert not any(r.command == "stimulate_analog" for r in adapter.command_log)


def test_must_be_connected():
    o = opened("valid_1_channel.json")
    runner = ProgramRunner(FakeCommunicationAdapter(), o.program, o.validation)
    with pytest.raises(RunRefused, match="Connect to the WSS first"):
        runner.start()


def test_real_hardware_is_refused_for_now():
    class Hardware(FakeCommunicationAdapter):
        mode = "hardware"

    o = opened("valid_1_channel.json")
    adapter = Hardware()
    adapter.connect()
    with pytest.raises(RunRefused, match="real WSS isn't enabled yet"):
        ProgramRunner(adapter, o.program, o.validation).start()
    assert not adapter.stimulating


def test_lost_connection_mid_run_is_an_error_and_stops():
    o = opened("matlab/ramp_2ch.mat")
    adapter = connected(disconnect_after_commands=10)  # drops part-way through
    runner = ProgramRunner(adapter, o.program, o.validation)
    runner.start()
    while runner.step():
        pass
    assert runner.state is RunState.ERROR
    assert "Stimulation stopped" in runner.detail
    assert not adapter.stimulating
    assert runner.position < 201


def test_stop_when_nothing_is_running_is_safe():
    o = opened("valid_1_channel.json")
    adapter = connected()
    runner = ProgramRunner(adapter, o.program, o.validation)
    runner.stop()
    assert runner.state is RunState.READY
    assert adapter.command_log[-1].command == "stop_stimulation"


def test_can_run_again_after_finishing():
    adapter = connected()
    program = series_program(3)
    runner = ProgramRunner(adapter, program, ValidationEngine(TEST_RANGES).validate(program))
    for _ in range(2):
        runner.start()
        while runner.step():
            pass
        assert runner.state is RunState.COMPLETE


# ------------------------------------------------------------------ screen


@pytest.fixture(scope="module")
def app():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def window_for(path, adapter):
    from ui.execution_window import ExecutionWindow

    w = ExecutionWindow(opened(path), adapter)
    w._timer.setInterval(10_000)  # tests drive the steps by hand
    return w


def test_screen_runs_a_time_series_and_shows_progress(app):
    adapter = connected()
    w = window_for("matlab/ramp_2ch.mat", adapter)
    assert w.state_label.text() == "State: Ready"
    assert w.run_button.isEnabled()
    w.run()
    w._tick()
    assert w.state_label.text() == "State: Running"
    assert w.progress_label.text().startswith("Step 2 of 201")
    assert w.table.item(0, 1).text() == "Stimulating"
    assert "stimulate_analog(channel=2" in w.log_view.toPlainText()
    assert not w.run_button.isEnabled()
    for _ in range(300):
        w._tick()
    assert w.state_label.text() == "State: Complete"
    assert w.table.item(0, 1).text() == "Off"
    w.close()


def test_stop_button_stops_and_says_so(app):
    adapter = connected()
    w = window_for("valid_4_channel.json", adapter)
    w.run()
    assert [w.table.item(r, 1).text() for r in range(4)] == ["Stimulating"] * 4
    w.stop_button.click()
    assert w.state_label.text() == "State: Stopped"
    assert w.detail_label.text() == "Stopped by user."
    assert not adapter.stimulating
    w.close()


def test_screen_refuses_unvalidated_program_and_explains(app):
    w = window_for("unsafe_amplitude.json", connected())
    assert not w.run_button.isEnabled()
    assert "failed validation" in w.reason_label.text()
    assert w.stop_button.isEnabled()  # STOP is always available
    w.close()


def test_connection_lost_during_run_is_shown(app):
    adapter = connected()
    w = window_for("matlab/ramp_2ch.mat", adapter)
    w.run()
    adapter.simulate_disconnect("cable pulled")
    app.processEvents()
    assert w.state_label.text() == "State: Error"
    assert "Connection lost: cable pulled" in w.detail_label.text()
    assert not w._timer.isActive()
    w.close()


def test_closing_the_screen_stops_a_run(app):
    adapter = connected()
    w = window_for("valid_1_channel.json", adapter)
    w.run()
    assert adapter.stimulating
    w.close()
    assert not adapter.stimulating
    assert w.runner.state is RunState.STOPPED


def test_main_menu_run_button_follows_validation(app, tmp_path):
    from ui.main_menu import MainMenuWindow

    with patch("ui.main_menu.RECENT_PROGRAMS_FILE", tmp_path / "recent.json"):
        menu = MainMenuWindow(ProgramFileManager(ValidationEngine(TEST_RANGES)), connected())
        assert not menu.run_button.isEnabled()
        menu.open_program_file(SAMPLES / "unsafe_amplitude.json")
        assert not menu.run_button.isEnabled()
        assert "failed validation" in menu.run_hint.text()
        menu.open_program_file(SAMPLES / "matlab" / "ramp_2ch.mat")
        assert menu.run_button.isEnabled()
        menu.run_button.click()
        assert menu.execution_window is not None
        assert menu.execution_window.opened.path.name == "ramp_2ch.mat"
        menu.execution_window.run()
        menu.close()  # closing the menu closes the screen and stops output
        assert not menu.adapter.stimulating


def test_main_menu_without_adapter_cannot_run(app, tmp_path):
    from ui.main_menu import MainMenuWindow

    with patch("ui.main_menu.RECENT_PROGRAMS_FILE", tmp_path / "recent.json"):
        menu = MainMenuWindow(ProgramFileManager(ValidationEngine(TEST_RANGES)))
        menu.open_program_file(SAMPLES / "valid_1_channel.json")
        assert not menu.run_button.isEnabled()
        assert "No WSS connection" in menu.run_hint.text()
        menu.close()
