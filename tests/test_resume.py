"""Resume after STOP: STOP still turns output off at once; afterwards a
stopped time series can continue from where it stopped instead of starting
over. Resuming ramps the amplitude back up from 0, re-checks everything Run
checks, and isn't offered after a lost connection, an error, or a finished
program. "Restart from 0 s" is always the other choice."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from channels import ProgramRunner, RunRefused, RunState, build_frames, ramp_frames  # noqa: E402
from comms import FakeCommunicationAdapter  # noqa: E402
from files import Channel, Program, ProgramFileManager, TimeSeriesPoint  # noqa: E402
from validation import RangeTable, ValidationEngine  # noqa: E402

TEST_RANGES = RangeTable.from_dict({
    "source": "test limits", "confirmed": True,
    "parameters": {
        "pulse_width": {"label": "pulse width", "unit": "µs", "min": 20, "max": 100},
        "amplitude": {"label": "amplitude", "unit": "mA", "min": 0, "max": 3},
        "frequency": {"label": "frequency", "unit": "Hz", "min": 1, "max": 50},
        "time_step": {"label": "time step", "unit": "ms", "min": 10, "max": 1000},
    },
})

#: 0.05 s ramp at a 10 ms step = 5 ramp-up frames (keeps tests short).
SHORT_RAMP = patch("channels.program_runner.RESUME_RAMP_S", 0.05)


def connected():
    adapter = FakeCommunicationAdapter()
    adapter.connect()
    return adapter


def program(n=10):
    """Ch1 ramps 0 -> 2.25 mA over n steps of 10 ms; ch2 is constant."""
    points = [TimeSeriesPoint(round(k * 0.01, 2), 50, round(k * 0.25, 2)) for k in range(n)]
    return Program("ts", "", 10, [Channel(1, 50, 0, 20, points), Channel(2, 40, 1, 25)])


def runner_for(prog=None, adapter=None):
    prog = prog or program()
    adapter = adapter or connected()
    return ProgramRunner(adapter, prog, ValidationEngine(TEST_RANGES).validate(prog)), adapter


def sent(adapter, channel=1):
    """Amplitudes sent to a channel, in order."""
    return [r.args["amplitude"] for r in adapter.command_log
            if r.command == "stimulate_analog" and r.args["channel"] == channel]


def run_steps(runner, k):
    runner.start()
    for _ in range(k - 1):
        runner.step()


# ------------------------------------------------------------------ runner


def test_stop_part_way_remembers_where_and_turns_output_off():
    runner, adapter = runner_for()
    run_steps(runner, 4)  # frames 0..3 sent; frame 3 (t = 0.03 s) is being output
    runner.stop()
    assert runner.state is RunState.STOPPED
    assert not adapter.stimulating
    assert adapter.command_log[-1].command == "stop_stimulation"
    assert runner.resume_time_s == pytest.approx(0.03)
    assert runner.detail == "Stopped by user at t = 0.03 s of 0.09 s. Output is off."
    assert runner.why_not_resumable() == ""


def test_resume_ramps_up_from_zero_then_continues_to_the_end():
    runner, adapter = runner_for()
    run_steps(runner, 4)
    runner.stop()
    before = len(sent(adapter))
    with SHORT_RAMP:
        runner.resume()
    assert runner.state is RunState.RUNNING and runner.is_ramping
    while runner.step():
        pass
    assert runner.state is RunState.COMPLETE
    after = sent(adapter)[before:]
    # 5 ramp frames toward frame 3's 0.75 mA, then frames 3..9 at full value
    assert after[:5] == pytest.approx([0.125, 0.25, 0.375, 0.5, 0.625])
    assert after[5:] == pytest.approx([0.75, 1.0, 1.25, 1.5, 1.75, 2.0, 2.25])


def test_ramp_keeps_pulse_width_and_frequency_and_scales_every_channel():
    frame = build_frames(program())[4]  # ch1 1.0 mA, ch2 1.0 mA
    ramp = ramp_frames(frame, 3)
    assert len(ramp) == 3
    for k, f in enumerate(ramp, start=1):
        for command, target in zip(f.commands, frame.commands):
            assert command.amplitude_ma == pytest.approx(target.amplitude_ma * k / 4)
            assert command.pulse_width_us == target.pulse_width_us
            assert command.frequency_hz == target.frequency_hz
            assert command.amplitude_ma < target.amplitude_ma


def test_ramp_length_follows_the_time_step():
    runner, _ = runner_for()
    run_steps(runner, 3)
    runner.stop()
    runner.resume()  # default 1 s ramp at 10 ms steps
    assert runner.ramp_total == 100
    assert runner.resume_target_s == pytest.approx(0.02)


def test_stop_during_the_ramp_resumes_toward_the_same_step():
    runner, adapter = runner_for()
    run_steps(runner, 6)
    runner.stop()
    with SHORT_RAMP:
        runner.resume()
        runner.step()
        runner.stop()
        assert runner.resume_time_s == pytest.approx(0.05)
        assert not adapter.stimulating
        runner.resume()
    assert runner.ramp_position == 1 and runner.ramp_total == 5


def test_restart_from_zero_forgets_the_resume_point():
    runner, adapter = runner_for()
    run_steps(runner, 5)
    runner.stop()
    runner.start()
    assert runner.position == 1 and runner.resume_time_s is None
    assert sent(adapter)[-1] == 0  # frame 0, no ramp


def test_nothing_to_resume_before_any_stop():
    runner, _ = runner_for()
    assert "nothing to resume" in runner.why_not_resumable()
    with pytest.raises(RunRefused, match="nothing to resume"):
        runner.resume()


def test_no_resume_after_the_program_finished():
    runner, _ = runner_for(program(3))
    runner.start()
    while runner.step():
        pass
    runner.stop()
    assert runner.state is RunState.COMPLETE
    assert runner.resume_time_s is None


def test_no_resume_after_a_lost_connection_during_the_run():
    runner, adapter = runner_for()
    run_steps(runner, 3)
    adapter.simulate_disconnect("cable pulled")
    runner.step()
    assert runner.state is RunState.ERROR
    assert runner.resume_time_s is None


def test_a_lost_connection_while_stopped_cancels_resume():
    runner, adapter = runner_for()
    run_steps(runner, 3)
    runner.stop()
    assert runner.resume_time_s is not None
    runner.connection_lost("cable pulled")
    assert runner.state is RunState.STOPPED
    assert runner.resume_time_s is None


def test_no_resume_after_a_device_error():
    class Breaks(FakeCommunicationAdapter):
        calls = 0

        def stimulate_analog(self, *a, **kw):
            Breaks.calls += 1
            if Breaks.calls == 3:
                raise RuntimeError("device busy")
            return super().stimulate_analog(*a, **kw)

    runner, _ = runner_for(adapter=Breaks())
    runner.adapter.connect()
    runner.start()
    runner.step()
    assert runner.state is RunState.ERROR
    assert runner.resume_time_s is None


def test_resume_rechecks_the_connection():
    runner, adapter = runner_for()
    run_steps(runner, 3)
    runner.stop()
    adapter.disconnect()
    assert runner.why_not_resumable() == "Connect to the WSS first."
    with pytest.raises(RunRefused):
        runner.resume()
    adapter.connect()
    runner.resume()
    assert runner.state is RunState.RUNNING


def test_a_constant_program_stops_without_a_resume_point():
    prog = Program("c", "", 10, [Channel(1, 50, 1, 20)])
    runner, _ = runner_for(prog)
    runner.start()
    runner.stop()
    assert runner.detail == "Stopped by user."
    assert runner.resume_time_s is None


# ------------------------------------------------------------------ screen


@pytest.fixture(scope="module")
def app():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def window(adapter):
    from ui.execution_window import ExecutionWindow

    opened = ProgramFileManager(ValidationEngine(TEST_RANGES)).open(
        ROOT / "samples" / "matlab" / "ramp_2ch.mat")  # 201 steps, 20 ms
    w = ExecutionWindow(opened, adapter)
    w._timer.setInterval(10_000)  # tests drive the steps by hand
    return w


def test_screen_offers_resume_and_restart_after_stop(app):
    adapter = connected()
    w = window(adapter)
    assert not w.resume_button.isVisible() and w.run_button.text() == "Run"
    w.run()
    for _ in range(99):
        w._tick()
    w.stop_button.click()
    assert w.state_label.text() == "State: Stopped"
    assert w.detail_label.text() == "Stopped by user at t = 1.98 s of 4 s. Output is off."
    assert w.progress_label.text().startswith("Step 100 of 201  ·  t = 1.98 s of 4 s")
    assert not w.resume_button.isHidden()
    assert w.resume_button.text() == "Resume from 1.98 s"
    assert w.resume_button.isEnabled()
    assert w.run_button.text() == "Restart from 0 s"
    assert [w.table.item(r, 1).text() for r in range(2)] == ["Off", "Off"]

    w.resume_button.click()
    assert w.state_label.text() == "State: Running"
    assert w.resume_button.isHidden()
    assert w.progress_label.text().startswith("Ramping back up to the values at t = 1.98 s (1 of 50)")
    assert float(w.table.item(0, 3).text()) < 2.475  # well below ch1's 2.475 mA at 1.98 s
    for _ in range(49):
        w._tick()
    w._tick()
    assert w.progress_label.text().startswith("Step 100 of 201")
    assert float(w.table.item(0, 3).text()) == pytest.approx(2.475)
    for _ in range(200):
        w._tick()
    assert w.state_label.text() == "State: Complete"
    assert w.resume_button.isHidden() and w.run_button.text() == "Run"
    w.close()


def test_screen_restart_runs_from_zero(app):
    w = window(connected())
    w.run()
    for _ in range(20):
        w._tick()
    w.stop()
    w.run_button.click()
    assert w.progress_label.text().startswith("Step 1 of 201")
    assert w.resume_button.isHidden()
    w.close()


def test_screen_hides_resume_after_a_lost_connection(app):
    adapter = connected()
    w = window(adapter)
    w.run()
    w._tick()
    w.stop()
    assert not w.resume_button.isHidden()
    adapter.simulate_disconnect("cable pulled")
    app.processEvents()
    assert w.resume_button.isHidden()
    assert w.run_button.text() == "Run"
    w.close()


def test_screen_resume_is_disabled_until_reconnected(app):
    adapter = connected()
    w = window(adapter)
    w.run()
    w._tick()
    w.stop()
    w.wss_status_bar.toggle_connection()  # Disconnect (not a lost link)
    app.processEvents()
    w.refresh()
    assert not w.resume_button.isHidden()
    assert not w.resume_button.isEnabled()
    assert w.resume_button.toolTip() == "Connect to the WSS first."
    w.wss_status_bar.toggle_connection()
    app.processEvents()
    w.refresh()
    assert w.resume_button.isEnabled()
    w.close()
