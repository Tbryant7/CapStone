# Command cheat sheet

Every command to run in the terminal (Cmder, PowerShell or Command Prompt).
Run them from the project folder, for example:

```
cd "C:\Users\<you>\OneDrive - Quinnipiac University\CapstoneProject"
```

macOS / Linux users: use `/` instead of `\` in paths, and
`source .venv/bin/activate` to activate the environment.

**Contents**

1. First-time setup
2. Every time you start working
3. Demo run-through (Sprint 1 and Sprint 2)
4. Test Pulse Window options
5. Fake WSS in the terminal
6. Check program files (ValidationEngine)
7. Safety limits file (ranges.json)
8. Change the test pulse values
9. Run the tests
10. Git: sharing your work
11. Open the project in VS Code
12. Troubleshooting

---

## 1. First-time setup (once per computer)

```
git clone --recursive https://github.com/Tbryant7/CapStone.git
cd CapStone
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

- `--recursive` also downloads the COSMIIC wrapper library into
  `external\wss-py-wrapper`. Already cloned without it? Run
  `git submodule update --init`.
- `python -m venv .venv` makes a private Python environment for this project.
- Only for `--simulated` or real hardware (needs .NET):
  `pip install -e external\wss-py-wrapper`
- If `python` isn't found, try `py` instead.

## 2. Every time you start working

```
cd "C:\Users\<you>\OneDrive - Quinnipiac University\CapstoneProject"
.venv\Scripts\activate
git checkout main
git pull
git submodule update --init
pip install -r requirements.txt
```

`git pull` gets your teammates' latest work. Re-running `pip install` is
quick and picks up any new packages someone added.

**To try work that isn't merged yet**, switch to its branch first, and go
back to `main` when you're done:

```
git fetch
git checkout sprint2/wss-status-bar
...
git checkout main
```

---

## 3. Demo run-through (Sprint 1 and Sprint 2)

Do sections 1-2 first, then `cls` to clear the screen before recording.
Everything here uses the fake WSS, so no hardware is needed.

### Sprint 1: Fake WSS (terminal)

```
python run_app.py --fake
```

At the `>` prompt, type these one at a time:

```
start
stim 1 0.5
drop
stim 1 0.5
reconnect
log
quit
```

Show: every command is logged; after `drop` the next command is
**rejected** ("CONNECTION LOST"); `log` lists everything, including the
rejected command; `quit` stops stimulation safely before exiting.

### Sprint 1: Test Pulse Window

```
python run_gui.py --fake
```

1. **Connect**: status turns green "Connected".
2. **Send Test Pulse**: output says "Stimulating on channel 1" and a log line appears.
3. **STOP**: output goes back to "Off".
4. **Send Test Pulse**, then **Simulate disconnect**: status turns red
   "Connection lost" and stimulation stops by itself.
5. **Connect** again to recover, then close the window.

### Sprint 2: Safe range config file

The safety limits live in one file. Show it:

```
type validation\ranges.json
```

Point out the min/max for pulse width, amplitude, frequency and time step,
and `"confirmed": false` (the numbers are placeholders until COSMIIC
confirms them). Every start prints a PLACEHOLDER warning until then.

Show that the app **refuses to start** without a valid limits file:

```
python run_gui.py --fake --ranges missing.json
python run_menu.py --ranges missing.json
```

Expected, for both: `Cannot start: Safe range file not found: missing.json`
and no window. Every way of starting the app (Test Pulse Window, Main Menu,
terminal app) checks the limits file first.

### Sprint 2: ValidationEngine

Check the three sample programs against the limits:

```
python -m validation samples\valid_1_channel.json samples\valid_4_channel.json samples\unsafe_amplitude.json
```

Expected:

```
samples\valid_1_channel.json (Single channel test): PASSED

samples\valid_4_channel.json (Four channel test): PASSED

samples\unsafe_amplitude.json (Unsafe amplitude (demo)): FAILED
  - Channel 2 amplitude 40 mA is above the 3 mA limit.
```

Optional: show that limits change without touching code. Open
`validation\ranges.json`, change amplitude `"max": 3` to `50`, save, re-run
the command above (now everything passes), then put it back:

```
git restore validation\ranges.json
```

Now show the same check inside the app. The Main Menu runs every program
it opens through the ValidationEngine:

```
python run_menu.py samples\unsafe_amplitude.json
```

The Opened Program panel at the bottom shows "Validation: Failed (1 problem)",
the message "Channel 2 amplitude 40 mA is above the 3 mA limit.", and the 40
cell marked "out of range" in red. Then click **Import Program / MATLAB File**
and choose `valid_4_channel.json`: "Validation: Passed". Close the window.

Then show the automated tests (values at, just under and just over every
limit, empty program, missing values):

```
python -m pytest tests\test_validation_engine.py tests\test_range_table.py -v
```

### Sprint 2: WSS status bar

The status bar is on the Main Menu (and the Test Pulse Window):

```
python run_menu.py --fake --fake-channels 6
```

Click **Connect** at the right end of the bar: "WSS: Connected | Channels: 6".
Click **Disconnect** to go back. The steps below use the Test Pulse Window,
which also has **Simulate disconnect**:

```
python run_gui.py --fake --fake-channels 6
```

Watch the bar along the bottom of the window:

1. Before connecting: "WSS: Not connected | Channels: none (not connected)",
   plus a yellow **SIMULATED (fake mode)** label on the right.
2. **Connect**: "WSS: Connected | Channels: 6". The count comes from the
   (fake) device, not a hard-coded 4. Try `--fake-channels 3` to show it changes.
3. **Simulate disconnect**: "WSS: Connection lost (simulated disconnect)"
   right away.
4. **Connect** again: back to "Connected".

Every state is written in words; the color is only an extra cue.

To show an automatic drop without clicking anything:

```
python run_gui.py --fake --fake-disconnect-after 2
```

Click **Connect**, then **Send Test Pulse** once. That click sends two
commands (start, then the pulse), so the fake WSS drops right after it and
the bar switches to "Connection lost" by itself.

### Sprint 2: Open a program on the Main Menu

```
python run_menu.py
```

1. **Import Program / MATLAB File**: the picker opens in `samples\`.
   Choose `valid_1_channel.json`: the Opened Program panel shows 1 channel
   and "Validation: Passed".
2. Import `valid_4_channel.json`: 4 channels, "Passed".
3. Import `unsafe_amplitude.json`: "Validation: Failed (1 problem)", the line
   "Channel 2 amplitude 40 mA is above the 3 mA limit.", and the 40 cell
   marked "out of range" in red.
4. Import `damaged\missing_amplitude.json` (or `damaged\truncated.json`): an
   error says what's wrong, and the panel still shows the previous program
   (nothing half-loaded).
5. Click a program in **Recent Stimulation Programs**, then **Open Selected**:
   it opens again.

Shortcut: `python run_menu.py samples\unsafe_amplitude.json` opens it at start.

Then show the tests (round trip save/load, damaged files, the panel):

```
python -m pytest tests\test_program_file_manager.py tests\test_program_panel.py -v
```

---

## 4. Test Pulse Window options

| Command | What it does |
|---|---|
| `python run_gui.py --fake` | Window with the fake WSS. No hardware or .NET needed. **Use this one on your laptop.** |
| `python run_gui.py --fake --fake-channels 6` | Fake WSS that reports 6 channels (shown in the status bar) |
| `python run_gui.py --fake --fake-disconnect-after 3` | Fake WSS that drops the connection by itself after 3 commands |
| `python run_gui.py --fake --ranges path\to\ranges.json` | Use a different safety limits file |
| `python run_gui.py --simulated` | Wrapper's built-in test transport (needs .NET, the DLLs and the wrapper submodule) |
| `python run_gui.py` | Uses the mode in `config\app_config.json` (currently `fake`) |
| `python run_gui.py --comm-mode hardware` | Real WSS hardware (lab computer) |
| `python run_gui.py --help` | List every option |

## 5. Fake WSS in the terminal

```
python run_app.py --fake
```

| Type at the `>` prompt | What it does |
|---|---|
| `start` | Start stimulation |
| `stim 1 0.5` | Channel 1 at 50% (normalized 0 to 1) |
| `analog 2 200 3 25` | Channel 2: pulse width 200, amplitude 3, interval 25 |
| `stop` | Stop stimulation (always allowed) |
| `status` | Show connection and stimulation state |
| `log` | Show every command sent so far |
| `drop` | Fake a disconnect |
| `reconnect` | Connect again after a drop |
| `quit` | Stop safely and exit |

The same options work here: `--fake-channels`, `--fake-disconnect-after`,
`--ranges`, `--simulated`, `--help`.

Every run writes a log file to `logs\commands_<date>_<time>.log`.

## 6. Check program files (ValidationEngine)

| Command | What it does |
|---|---|
| `python -m validation samples\valid_4_channel.json` | Check one program file |
| `python -m validation samples\valid_1_channel.json samples\unsafe_amplitude.json` | Check several at once |
| `python -m validation my_program.json --ranges other_ranges.json` | Check against a different limits file |
| `python -m validation --help` | List every option |

Each file prints **PASSED** or **FAILED** with one plain-language line per
problem (out of range, missing value, not a number, duplicate channel,
empty program). It exits with an error code if any file fails.

Sample programs in `samples\`:

| File | Expected result |
|---|---|
| `valid_1_channel.json` | PASSED: one channel at low settings |
| `valid_4_channel.json` | PASSED: four channels inside the limits |
| `unsafe_amplitude.json` | FAILED: channel 2 amplitude 40 mA is over the limit |

To make your own, copy a sample and change the numbers. Units are in the
field names: `pulse_width_us` (µs), `amplitude_ma` (mA), `frequency_hz`
(Hz), `time_step_ms` (ms).

## 7. Safety limits file (ranges.json)

```
code validation\ranges.json
```

Edit the `min` / `max` numbers and save. No code changes are needed.

- The app **won't start** if the file is missing or broken, and the message
  says what's wrong.
- Until COSMIIC confirms the limits, keep `"confirmed": false`. The app
  prints a PLACEHOLDER warning on every start.
- When COSMIIC confirms them: put their numbers in, write where they came
  from in `"source"`, and set `"confirmed": true`.
- Undo your edits: `git restore validation\ranges.json`

## 8. Change the test pulse values

The Test Pulse Window's values are set in code, not in the window. Open:

```
code ui\pulse_window.py
```

Near the top, edit these, save, and re-run `python run_gui.py --fake`:

```python
TEST_CHANNEL = 1
TEST_PULSE_WIDTH = 50
TEST_AMPLITUDE = 1
TEST_IPI = 50
```

Confirm the values with COSMIIC before using real hardware.

---

## 9. Run the tests

| Command | What it does |
|---|---|
| `python -m pytest` | Run every test |
| `python -m pytest -v` | Same, listing each test by name |
| `python -m pytest tests\test_validation_engine.py` | ValidationEngine and `python -m validation` |
| `python -m pytest tests\test_range_table.py` | Safe range file and "refuses to start" |
| `python -m pytest tests\test_wss_status_bar.py` | WSS status bar and channel count |
| `python -m pytest tests\test_pulse_window_gui.py` | Test Pulse Window |
| `python -m pytest -k disconnect` | Only tests with "disconnect" in the name |
| `python -m pytest -rs` | Also say why skipped tests were skipped |

If 6 tests are skipped, the wrapper submodule is missing: run
`git submodule update --init`.

---

## 10. Git: sharing your work

`main` is shared, so make changes on your own branch and open a pull request.

```
git checkout main
git pull
git checkout -b my-change-name
```

Edit files, then:

```
git status
git add .
git commit -m "Short description of the change"
git push -u origin my-change-name
```

Open the link Git prints (or go to the repo on GitHub) and click
**Create pull request**. After it's merged:

```
git checkout main
git pull
```

Handy extras:

| Command | What it does |
|---|---|
| `git status` | What's changed and which branch you're on |
| `git branch` | List your branches |
| `git log --oneline -10` | Last 10 commits |
| `git diff` | Exact lines you changed (press `q` to exit) |
| `git restore <file>` | Throw away your changes to one file |
| `git switch <branch>` | Move to another branch |

## 11. Open the project in VS Code

```
code .
```

---

## 12. Troubleshooting

| Problem | Fix |
|---|---|
| `external\wss-py-wrapper` is empty | `git submodule update --init` |
| `git pull` says local changes to `config/recent_programs.json` would be overwritten | `git restore config\recent_programs.json`, then `git pull` again (one time only; the file is no longer tracked) |
| Recent Stimulation Programs list is empty | Normal on a new laptop or after the update above: the list is kept per person and fills up as you open programs |
| `Cannot start: Safe range file ...` | `validation\ranges.json` is missing or has a mistake; the message says which. `git restore validation\ranges.json` puts it back |
| `WARNING: safety limits ... are PLACEHOLDERS` | Expected until COSMIIC confirms the limits (see section 7) |
| `No module named validation` / `files` | Run the command from the project folder, not from inside a subfolder |
| `No module named PySide6` or `pytest` | Activate the venv (`.venv\Scripts\activate`), then `pip install -r requirements.txt` |
| `unrecognized arguments: --fake-channels` (or `--ranges`) | You're on an older branch: `git checkout main` and `git pull` |
| `python` not recognized | Use `py` instead, or install Python from python.org and tick "Add to PATH" |
| `Could not connect in simulated mode` | You don't have .NET / the DLLs. Use `--fake` |
| `git push` rejected ("fetch first") | `git pull`, then push again |
| Window doesn't open from Cmder | Try a normal Command Prompt or PowerShell |
| Weird Git errors in OneDrive | Pause OneDrive syncing, or move the project to `C:\Users\<you>\Projects\` |
