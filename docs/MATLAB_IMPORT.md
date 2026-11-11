# Importing MATLAB / CSV time-series data

The Main Menu's **Import Program / MATLAB File** button opens `.mat` and
`.csv` files as well as `.json` programs (SRS REQ-15, use case "Import and
Execute a Stimulation Program"). The data becomes a program whose channels
change over time, and it is checked by the ValidationEngine like any other
program.

> **This layout is our proposal.** The SRS lists the format of the
> researcher's MATLAB output as still to be confirmed. If your pipeline
> saves different variable names or shapes, tell us and we'll match it.

## Stimulation matrix (.mat): total time, channels, time step

The simplest layout for MATLAB scripts. Choose:

1. the **total time length**, `total_time_s`
2. the **number of active channels**, `num_channels`
3. the **time step**, `time_step_ms` (optional: if left out it is
   `total_time_s / (rows - 1)`; `time_step_s` also works)

and save one matrix `stim`:

- **rows** = `total_time_s / time step + 1` (t = 0, dt, 2·dt, ..., total)
- **columns** = `num_channels x parameters per channel`, channel by channel:
  `[ch1_pw, ch1_amp, ch2_pw, ch2_amp, ...]`

| Columns per channel | Parameters (in order) |
|---|---|
| 1 | amplitude (mA) |
| 2 | pulse width (µs), amplitude (mA) |
| 3 | pulse width (µs), amplitude (mA), frequency (Hz) |

A parameter that isn't in `stim` is its own variable, one value or one per
channel. For example, with 2 columns per channel, save `frequency_hz = 20`.
Frequency must stay the same down a channel's column.

| Optional | Meaning |
|---|---|
| `parameters` | Column order as a cell array, e.g. `{'amplitude_ma','pulse_width_us'}` |
| `column_order = 'parameter'` | Group columns by parameter instead: `[all pw, all amp]` |
| `channels` | Channel numbers, default `1..num_channels` |
| `name`, `description` | Shown on the Main Menu |

```matlab
total_time_s = 3; num_channels = 3; time_step_ms = 20;
t = (0:time_step_ms/1000:total_time_s)';            % 151 rows
stim = zeros(numel(t), num_channels * 2);           % pw, amp per channel
for ch = 1:num_channels
    stim(:, 2*ch-1) = 50;                            % pulse width, us
    stim(:, 2*ch)   = min(t / 1.5, 1) * 2.0;         % amplitude ramp to 2 mA
end
frequency_hz = 20;
save('stim_matrix_3ch.mat', 'stim', 'total_time_s', 'num_channels', ...
     'time_step_ms', 'frequency_hz', '-v7');
```

The full example is `samples/matlab/make_stim_matrix.m`, and its output is
`samples/matlab/stim_matrix_3ch.mat`. If the row count doesn't match
`total_time_s / time step + 1`, the columns don't divide into the channels,
or something is missing, the import is refused and the message gives the
numbers it expected.

The **New Program** screen uses the same three settings (Total time, Active
channels, Time step), and **Export .mat...** writes this layout with all
three parameters per channel. A file made in the app opens in MATLAB, and a
file made in MATLAB opens in the app.

## From MATLAB (.mat): separate variables

The original layout still works. Save these variables (see
`samples/matlab/make_example.m`):

| Variable | Shape | Meaning |
|---|---|---|
| `time_s` | N values (row or column) | Seconds from the start. One fixed step apart, e.g. 0, 0.02, 0.04, ... |
| `amplitude_ma` | N x C (one column per channel) | Amplitude in mA at each time. A single value or 1 x C means constant. |
| `pulse_width_us` | N x C, 1 x C or one value | Pulse width in µs. |
| `frequency_hz` | 1 x C or one value | Stimulation frequency in Hz (constant per channel). |
| `channels` | 1 x C, optional | Channel numbers. Default 1, 2, ..., C. |
| `name`, `description` | text, optional | Shown on the Main Menu. Default: the file name. |

Short names also work: `t`/`time`, `amp`/`amplitude`, `pw`/`pulse_width`,
`freq`/`frequency`. Channels given as rows instead of columns are turned
around automatically.

```matlab
dt = 0.020;
time_s = (0:dt:4)';
amplitude_ma = [min(time_s/2, 1) * 2.5, min(max((time_s-1)/2, 0), 1) * 2.0];
pulse_width_us = 50;
frequency_hz = [20, 25];
save('ramp_2ch.mat', 'time_s', 'amplitude_ma', 'pulse_width_us', 'frequency_hz', '-v7');
```

Use `-v7` (MATLAB's default). Files saved with `-v7.3` can't be read yet;
the app says so and tells you how to re-save.

## From CSV

A header row, then one row per time step:

```
time_s,ch1_amplitude_ma,ch1_pulse_width_us,ch1_frequency_hz,ch2_amplitude_ma,ch2_pulse_width_us,ch2_frequency_hz
0,0,50,20,0,50,25
0.02,0.025,50,20,0,50,25
...
```

Every channel needs all three columns. `chN_frequency_hz` must be the same
on every row.

## What gets checked

**When importing (all or nothing).** If anything required is missing, the
shapes don't line up, a value isn't a number, or the file is damaged, the
import is refused with every problem listed, and nothing is loaded. The
program on screen doesn't change.

**After importing (ValidationEngine).** The program opens and shows
"Validation: Passed" or the list of problems:

- every point's pulse width and amplitude against `validation/ranges.json`
  (one summary line per channel, e.g. "Channel 1 amplitude goes above the
  3 mA limit at 470 time-series points (highest 25 mA at t = 0.25 s)")
- the time step against its safe range
- times in order, starting at 0 or later, and exactly one time step apart
  (SRS UC2-A2)
- frequency, channel numbers and duplicates, as for any program

## Try it

```
python -m validation samples\matlab\stim_matrix_3ch.mat samples\matlab\ramp_2ch.mat samples\matlab\ramp_2ch.csv samples\matlab\client_example_25ma.mat samples\matlab\missing_frequency.mat
python run_menu.py samples\matlab\ramp_2ch.mat
```

| Sample | Result |
|---|---|
| `stim_matrix_3ch.mat` | PASSED: stim-matrix layout, 3 s, 20 ms step (151 rows), 3 channels x (pw, amp) |
| `ramp_2ch.mat` / `ramp_2ch.csv` | PASSED: two channels ramping up over 4 s, 20 ms step |
| `client_example_25ma.mat` | FAILED: the Vision Document's example (20 µs, 25 mA, 1 ms step) is outside the **placeholder** limits |
| `missing_frequency.mat` | Not imported: `frequency_hz` is missing |

`python tools/make_matlab_samples.py` rebuilds the sample files.

## Not done yet

- MATLAB v7.3 (HDF5) files
- Running a time series on the WSS (Sprint 5: "Run the time-series pattern")
- Graph preview of the time series (REQ-9)
