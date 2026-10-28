# COSMIIC WSS App (Capstone)

A PySide6 desktop app for building and running stimulation programs on the
COSMIIC Wireless Stimulation System (WSS).

## Setup

You need Python 3.10 or newer and Git.

```bash
git clone --recursive https://github.com/Tbryant7/CapStone.git
cd CapStone
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate      # macOS / Linux
pip install -r requirements.txt
```

`--recursive` also downloads the COSMIIC wrapper library
([HFI_WSS_Python_Interface](https://github.com/cwru-non-academic/HFI_WSS_Python_Interface))
into `external/wss-py-wrapper`, the same way
[CLI_Python_WSS_Application](https://github.com/cwru-non-academic/CLI_Python_WSS_Application)
does. If you already cloned without it, run:

```bash
git submodule update --init
```

Fake mode needs only the steps above. To run against the real WSS or the
wrapper's simulated transport (`--simulated`), also install the wrapper and
pythonnet, and have a .NET runtime:

```bash
pip install -e external/wss-py-wrapper
```

## Run it

See [COMMANDS.md](COMMANDS.md) for every terminal command in one place.

```bash
python run_gui.py --fake      # Test Pulse Window, no hardware needed
python run_app.py --fake      # console version
python -m pytest              # all tests
```

### Test Pulse Window

Pick a serial port (or Auto-detect), click **Connect**, then **Send Test
Pulse** to start a pulse train on channel 1 with fixed low values. The red
**STOP** button is always enabled. The status line says in words whether the
WSS is connected, not connected or lost, and the window checks the link every
second so it notices an unplugged device. In fake and simulated modes a yellow
banner says so, and **Simulate disconnect** lets you test the lost state.
Every command appears in the log at the bottom and in `logs/`.

The test pulse values (pulse width 50, amplitude 1, interval 50) are
placeholders in `ui/pulse_window.py`. Confirm them and their units against
the COSMIIC safe ranges before using hardware on a person.

## Folders (SDS Section 2.2)

```
ui/          PySide6 windows and screens
editor/      Beginner and Advanced program editors
files/       ProgramFileManager (JSON save/load)
timeseries/  time-varying stimulation patterns
validation/  RangeTable and ValidationEngine
channels/    multi-channel manager
comms/       CommunicationAdapter: the only code that talks to the WSS
samples/     sample program files (two valid, one unsafe for the demo)
docs/        notes and help content
tests/       automated tests
```

## WSS status bar (Sprint 2)

`ui/wss_status_bar.py` is a status bar for any window:
`window.setStatusBar(WssStatusBar(adapter))`. It shows, in words, whether the
WSS is connected, not connected or lost, and the channel count the device
reports (`adapter.channel_count()`, not a hard-coded 4). It shows a
SIMULATED label in fake and simulated modes. It updates on every connection
change and re-checks every 2 seconds, so an unplugged WSS shows within a few
seconds. It's on the Main Menu (`python run_menu.py --fake`), with its own
Connect button, and in the Test Pulse Window. Try `python run_gui.py --fake --fake-channels 6`.

On the real WSS the channel count comes from asking the device which
channels are valid (`IsFingerValid("ch1")`, `"ch2"`, ...). This hasn't been
checked on hardware yet.

## Safety limits and validation (Sprint 2)

All safety limits live in `validation/ranges.json`: the min and max for pulse
width (µs), amplitude (mA), frequency (Hz) and time step (ms). The app will
not start if that file is missing or broken.

**The numbers in it now are placeholders, not COSMIIC limits.** The file says
so (`"confirmed": false`), and the app prints a warning at startup until it
is changed. When COSMIIC confirms the limits, edit the numbers, write where
they came from in `"source"`, and set `"confirmed": true`. No code changes
are needed.

`ValidationEngine` (in `validation/`) checks a program against those limits
and returns `is_valid` plus plain-language messages such as
"Channel 2 amplitude 40 mA is above the 3 mA limit." Every path that loads or
saves a program must call it (REQ-16, REQ-17):

```python
from validation import ValidationEngine
result = ValidationEngine().validate(program)
if not result.is_valid:
    show(result.failed_parameters)   # don't save or run it
```

A program is the `Program` / `Channel` data classes in `files/program.py`,
which ProgramFileManager saves and loads as JSON. See `samples/` for the format.

## ProgramFileManager (Sprint 2)

```python
from files import ProgramFileManager, ProgramFileError
manager = ProgramFileManager()
manager.save(program, "my_program.json")   # refuses a program that fails validation
program = manager.load("my_program.json")  # ProgramFileError if damaged or incomplete
opened = manager.open("my_program.json")   # opened.program + opened.validation
```

Loading is all or nothing: the whole file is checked first, and a damaged
(not valid JSON, cut off) or incomplete (a missing or empty field) file
raises `ProgramFileError` with a plain-language reason. Nothing is
half-loaded. A complete file with unsafe values still opens, so the screen
can show why it fails. Saving writes to a temporary file first, so a failed
save never damages the old file. `samples/damaged/` has two broken files for
the demo.

## Opened Program panel (Sprint 2)

```bash
python run_menu.py                                 # Main Menu
python run_menu.py samples/unsafe_amplitude.json   # open a program straight away
```

**Import Program** (or **Open Selected** on a recent program) opens a program
file and shows it, read-only, at the bottom of the Main Menu: its name, each
channel's pulse width, amplitude and frequency, and the validation result,
"Passed" or each failing value in words. Out-of-range cells are also marked
"out of range" in red. A damaged file shows an error and the panel keeps
what it was showing. The panel (`ui/program_panel.py`) is a placeholder
until the Beginner Editor arrives in Sprint 3.

The Recent Stimulation Programs list is saved in
`config/recent_programs.json`. That file is per person and is not in Git
(it's in `.gitignore`), so everyone keeps their own list and opening a
program never shows up as a change in `git status`.

## MATLAB / CSV import (REQ-15)

**Import Program / MATLAB File** on the Main Menu also opens `.mat` and
`.csv` time-series files. Each channel gets a time series of pulse width and
amplitude, and the ValidationEngine checks every point, the time step, and
that points are in order and evenly spaced. A file with anything missing is
refused and nothing is half-loaded. The expected layout is in
[docs/MATLAB_IMPORT.md](docs/MATLAB_IMPORT.md) (our proposal until the
client confirms his MATLAB output); samples are in `samples/matlab/`.

## Working as a team

`main` is protected: make a branch, push it, and open a pull request.

```bash
git checkout -b my-feature
git push -u origin my-feature
```

## Communication Adapter: simulated mode (Sprint 1)

This adds a way to run the app without WSS hardware, using one setting.

## What we checked first

**Can the wrapper's `--test` mode be turned on from code? Yes.**

`--test` in the CLI only does this:

```python
config = replace(config, test_mode=True)
```

`test_mode` is a plain field on `wss_py_wrapper.WssConfig`. When it is set,
`StimulationController._create_transport()` builds the C# `TestModeTransport`
instead of `SerialPortTransport`. Everything above the transport is the real
code path: framing, setup sequence, params layer and model layer.

That mode alone does **not** meet two of the "done when" items:

| Requirement | Wrapper `test_mode` on its own |
|---|---|
| Logs every command | Partly. It logs raw frame bytes (`Out: c0 0a ...`) to the C# log file. You can't read which command each frame is. |
| Fake disconnect | No. The wrapper never exposes the transport object, so Python cannot tell it to drop. |
| Runs without .NET | No. It still needs pythonnet, a .NET runtime and the DLLs. |

So both were built:

1. A `simulated` option on the real adapter. It sets `test_mode=True`.
2. A `FakeCommunicationAdapter`. It is pure Python and runs on any laptop.

Logging and fake disconnect live in the shared base class, so **both modes
meet all three done criteria**.

## The one setting

```bash
python run_app.py --fake          # pure Python, no .NET needed
python run_app.py --simulated     # wrapper test transport (needs .NET and DLLs)
python run_app.py                 # uses config/app_config.json, else hardware
```

Or in `config/app_config.json`:

```json
{ "communication": { "mode": "fake" } }
```

The command-line flag wins over the config file. The default is `hardware`.

## Done criteria

* **One setting:** `--fake`, `--simulated` or `"mode"` in the config.
* **Logs every command:** every call is logged with its arguments and outcome
  (`ok`, `rejected: connection lost`, `error: ...`). Rejected commands are
  logged too. The log goes to the console and to `logs/commands_<time>.log`.
  It is also kept in memory as `adapter.command_log`, so the GUI can show it.
* **Fake disconnect:**
  * `adapter.simulate_disconnect()`: drop the link now. The console command is `drop`.
  * `FakeCommunicationAdapter(disconnect_after_commands=N)`, or the
    `--fake-disconnect-after N` flag: drop the link after N commands.
    Use this for repeatable tests.
  * `disconnect_after_seconds=T` in the config: drop the link on a timer.

  After a drop, every command raises `ConnectionLostError` and status
  listeners get `state=lost`. `stop_stimulation()` never raises, because it
  is the safety path (REQ-19). `connect()` reconnects. A fake disconnect is
  **refused in hardware mode**.

## Using it from the GUI

```python
from comms import load_app_config, resolve_mode, create_adapter, ConnectionLostError

cfg = load_app_config(Path("config/app_config.json"))
adapter = create_adapter(resolve_mode(cli_mode, cfg), cfg)
adapter.add_status_listener(update_status_bar)   # runs on connect/start/stop/lost
adapter.connect()
adapter.stimulate(channel=2, magnitude=0.5)      # normalized 0..1, goes through the params layer
adapter.stimulate_analog(1, pulse_width=200, amplitude=3, ipi=25)
```

The GUI and the other layers only call `comms`. They never import
`wss_py_wrapper` directly.

## Layout

```
comms/
  base.py           CommunicationAdapter: logging, connection state, fake disconnect
  wss_adapter.py    WssCommunicationAdapter(simulated=...) -> wss_py_wrapper
  fake_adapter.py   FakeCommunicationAdapter (no .NET)
  factory.py        --comm-mode / --simulated / --fake, config lookup, log file setup
run_app.py          console entry point until the GUI exists
config/app_config.json
tests/test_adapters.py   22 tests, no hardware or .NET needed
tests/test_card_api.py   connect(port), send_test_pulse, stop, unplug detection
tests/test_pulse_window_gui.py   Test Pulse Window, off-screen
```

`external/wss-py-wrapper` is the wrapper submodule
(`HFI_WSS_Python_Interface`), pinned to the same commit as
`CLI_Python_WSS_Application`.

## Tests

```bash
pip install pytest
python -m pytest tests
```

The wrapper tests use the real `WssConfig` and the real
`StimulationController._create_transport()`, with dummy .NET types. They
confirm that `simulated` really selects `TestModeTransport`.

## Known issues / follow-ups

1. **`--simulated` has not been run against the real DLLs yet.** Try it on a
   Windows lab machine:
   ```bash
   python run_app.py --simulated
   ```
   Then check `logs/wss_*.log` for the `Out:` frame lines.
2. **Updating the DLLs will break the wrapper's test mode.** The bundled
   `WSS_Core_Interface.dll` is from Apr 11. On Apr 15, `WSSCoreInterface`
   (commit a9b8427, "options pattern") changed `TestModeTransport` so it
   requires a `TestModeTransportOptions` argument. The wrapper still calls
   `TestModeTransport()` with no arguments. If anyone pulls newer DLLs,
   `--simulated` and the CLI's `--test` will both fail until the wrapper is
   patched to `TestModeTransport(TestModeTransportOptions())`. Fake mode is
   not affected.
3. **`Ready()` is true only for a moment.** The C# core's `Ready()` is true
   only while it is in the Ready state. Setup ends with `StartStim`, so the
   core moves on to Started. `connect()` therefore waits for
   `Ready() or Started()`, with a 10 s timeout.
4. **Channel checks.** The adapter only rejects channel numbers below 1.
   Range checks (for example, at most 4 channels) belong in the Validation &
   Safety Engine (REQ-16/23).
