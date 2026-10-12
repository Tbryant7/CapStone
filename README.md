# Communication Adapter: simulated mode (Sprint 1)

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
from communication import load_app_config, resolve_mode, create_adapter, ConnectionLostError

cfg = load_app_config(Path("config/app_config.json"))
adapter = create_adapter(resolve_mode(cli_mode, cfg), cfg)
adapter.add_status_listener(update_status_bar)   # runs on connect/start/stop/lost
adapter.connect()
adapter.stimulate(channel=2, magnitude=0.5)      # normalized 0..1, goes through the params layer
adapter.stimulate_analog(1, pulse_width=200, amplitude=3, ipi=25)
```

The GUI and the other layers only call `communication`. They never import
`wss_py_wrapper` directly.

## Layout

```
communication/
  base.py           CommunicationAdapter: logging, connection state, fake disconnect
  wss_adapter.py    WssCommunicationAdapter(simulated=...) -> wss_py_wrapper
  fake_adapter.py   FakeCommunicationAdapter (no .NET)
  factory.py        --comm-mode / --simulated / --fake, config lookup, log file setup
run_app.py          console entry point until the GUI exists
config/app_config.json
tests/test_adapters.py   22 tests, no hardware or .NET needed
```

`external/wss-py-wrapper` is expected to be the wrapper submodule, the same
layout as `CLI_Python_WSS_Application`.

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
