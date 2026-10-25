# Command cheat sheet

Every command to run in the terminal (Cmder, PowerShell or Command Prompt).
Run them from the project folder, for example:

```
cd "C:\Users\<you>\OneDrive - Quinnipiac University\CapstoneProject"
```

macOS / Linux users: use `/` instead of `\` in paths, and see the notes in
each section.

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
- macOS / Linux: activate with `source .venv/bin/activate`.
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

---

## 3. Run the Test Pulse Window (GUI)

| Command | What it does |
|---|---|
| `python run_gui.py --fake` | Open the window with the fake WSS. No hardware or .NET needed. **Use this one on your laptop.** |
| `python run_gui.py --fake --fake-disconnect-after 3` | Fake WSS that drops the connection by itself after 3 commands |
| `python run_gui.py --simulated` | Wrapper's built-in test transport (needs .NET, the DLLs and the wrapper submodule) |
| `python run_gui.py` | Uses the mode in `config\app_config.json` (currently `fake`) |
| `python run_gui.py --comm-mode hardware` | Real WSS hardware (lab computer) |
| `python run_gui.py --help` | List every option |

In the window: **Connect**, then **Send Test Pulse**, then **STOP**.
**Simulate disconnect** tests the "Connection lost" state.

## 4. Run the fake WSS in the terminal (no window)

```
python run_app.py --fake
```

Then type these at the `>` prompt:

| Type | What it does |
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

Other options work here too: `--simulated`, `--fake-disconnect-after 3`, `--help`.

Every run writes a log file to `logs\commands_<date>_<time>.log`.

## 5. Change the test pulse values

The values are in code, not in the window. Open the file:

```
code ui\pulse_window.py
```

Edit lines 34-37, save, and re-run `python run_gui.py --fake`:

```python
TEST_CHANNEL = 1
TEST_PULSE_WIDTH = 50
TEST_AMPLITUDE = 1
TEST_IPI = 50
```

Confirm the values with COSMIIC before using real hardware.

To make the fake WSS the default (so plain `python run_gui.py` uses it),
set `"mode": "fake"` in `config\app_config.json`. It's already set that way.

---

## 5b. Change the safety limits

Open the limits file, edit the min/max numbers, and save:

```
code validation\ranges.json
```

The app won't start if the file is missing or broken, and prints a
PLACEHOLDER warning until `"confirmed"` is set to `true`. To check a
different limits file without editing the real one:

```
python run_gui.py --fake --ranges path\to\other_ranges.json
```

## 6. Run the tests

| Command | What it does |
|---|---|
| `python -m pytest` | Run every test |
| `python -m pytest -v` | Same, listing each test by name |
| `python -m pytest tests\test_pulse_window_gui.py` | Only the window tests |
| `python -m pytest -k disconnect` | Only tests with "disconnect" in the name |
| `python -m pytest tests\test_validation_engine.py` | Only the ValidationEngine tests |
| `python -m pytest -rs` | Also say why skipped tests were skipped |

If 6 tests are skipped, the wrapper submodule is missing: run
`git submodule update --init`.

---

## 7. Git: sharing your work

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

---

## 8. Open the project in VS Code

```
code .
```

---

## Troubleshooting

| Problem | Fix |
|---|---|
| `external\wss-py-wrapper` is empty | `git submodule update --init` |
| `Cannot start: Safe range file ...` | `validation\ranges.json` is missing or has a mistake; the message says which |
| `No module named PySide6` or `pytest` | Activate the venv (`.venv\Scripts\activate`), then `pip install -r requirements.txt` |
| `python` not recognized | Use `py` instead, or install Python from python.org and tick "Add to PATH" |
| `Could not connect in simulated mode` | You don't have .NET / the DLLs. Use `--fake` |
| `git push` rejected ("fetch first") | `git pull`, then push again |
| Window doesn't open from Cmder | Try a normal Command Prompt or PowerShell |
| Weird Git errors in OneDrive | Pause OneDrive syncing, or move the project to `C:\Users\<you>\Projects\` |
