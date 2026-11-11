"""Rebuild the sample files in samples/matlab/ (python tools/make_matlab_samples.py).

They are what MATLAB would write with samples/matlab/make_example.m.
"""

from __future__ import annotations

import csv
from pathlib import Path

import numpy as np
from scipy.io import savemat

OUT = Path(__file__).resolve().parents[1] / "samples" / "matlab"


def ramp_2ch():
    t = np.round(np.arange(0, 4.0 + 1e-9, 0.020), 6)            # 4 s, 20 ms step
    a1 = np.clip(t / 2.0, 0, 1) * 2.5                             # ch1: 0 -> 2.5 mA over 2 s
    a2 = np.clip((t - 1.0) / 2.0, 0, 1) * 2.0                     # ch2: starts at 1 s, -> 2 mA
    amplitude = np.round(np.column_stack([a1, a2]), 4)
    return t, amplitude


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    t, amplitude = ramp_2ch()
    savemat(OUT / "ramp_2ch.mat", {
        "time_s": t.reshape(-1, 1),
        "amplitude_ma": amplitude,
        "pulse_width_us": np.array([[50.0]]),
        "frequency_hz": np.array([[20.0, 25.0]]),
        "name": "Two channel ramp (demo)",
        "description": "Ch1 ramps to 2.5 mA, ch2 to 2 mA. Should pass validation.",
    }, format="5")

    with open(OUT / "ramp_2ch.csv", "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["time_s",
                         "ch1_amplitude_ma", "ch1_pulse_width_us", "ch1_frequency_hz",
                         "ch2_amplitude_ma", "ch2_pulse_width_us", "ch2_frequency_hz"])
        for k, time in enumerate(t):
            writer.writerow([f"{time:g}", f"{amplitude[k, 0]:g}", 50, 20,
                             f"{amplitude[k, 1]:g}", 50, 25])

    # The client's example from the Vision Document: 20 us, 25 mA, 1 ms step.
    tc = np.round(np.arange(0, 0.5 + 1e-9, 0.001), 6)
    savemat(OUT / "client_example_25ma.mat", {
        "time_s": tc.reshape(-1, 1),
        "amplitude_ma": np.round(np.clip(tc / 0.25, 0, 1) * 25.0, 4).reshape(-1, 1),
        "pulse_width_us": np.array([[20.0]]),
        "frequency_hz": np.array([[20.0]]),
        "name": "Client example: 20 us, 25 mA, 1 ms step",
        "description": "Vision Document example. Fails the PLACEHOLDER limits (3 mA, 10 ms min step).",
    }, format="5")

    # Incomplete on purpose: no frequency. Import must refuse it.
    savemat(OUT / "missing_frequency.mat", {
        "time_s": t.reshape(-1, 1),
        "amplitude_ma": amplitude,
        "pulse_width_us": np.array([[50.0]]),
        "name": "Missing frequency (demo)",
    }, format="5")
    stim_matrix_sample()
    per_channel_sample()
    print(f"Wrote samples to {OUT}")


def stim_matrix_sample() -> None:
    """The stim-matrix layout (files/stim_matrix.py), as make_stim_matrix.m writes it.

    3 s at a 20 ms step -> 151 rows; 3 channels x (pulse width, amplitude) -> 6 columns.
    """
    total, step_ms, n_channels = 3.0, 20.0, 3
    t = np.round(np.arange(int(round(total * 1000 / step_ms)) + 1) * step_ms / 1000, 6)
    columns = []
    for ch in range(n_channels):
        start = ch * 0.5                                            # each channel starts 0.5 s later
        columns += [np.full(t.size, 50.0),                          # pulse width, us
                    np.round(np.clip((t - start) / 1.5, 0, 1) * 2.0, 4)]   # ramp to 2 mA over 1.5 s
    savemat(OUT / "stim_matrix_3ch.mat", {
        "stim": np.column_stack(columns),
        "total_time_s": total,
        "num_channels": float(n_channels),
        "time_step_ms": step_ms,
        "frequency_hz": 20.0,
        "name": "Three channel stim matrix (demo)",
        "description": "Rows = total time / time step + 1, columns = channels x (pw, amp).",
    }, format="5")


def per_channel_sample() -> None:
    """Prof. LaMack's layout: t, pw1, a1, freq1, pw2, a2, freq2 in s / A / Hz
    (samples/matlab/make_per_channel.m). Frequency changes over time."""
    t = np.round(np.arange(0, 10.0 + 1e-9, 0.020), 6)              # 10 s, 20 ms step
    env = np.minimum(np.clip(t / 2, 0, 1), np.clip((10 - t) / 2, 0, 1))
    variables = {
        "t": t,
        "pw1": np.round(0.0001 * (0.5 + 0.5 * env), 9),              # 50 -> 100 us, in seconds
        "a1": np.round(0.002 * env, 9),                              # 0 -> 2 mA, in amps
        "freq1": np.round(20 + 10 * env, 6),                         # 20 -> 30 Hz
        "pw2": np.full_like(t, 0.00005),                             # 50 us
        "a2": np.round(0.0015 * np.clip((t - 1) / 3, 0, 1) * (t < 8), 9),   # 0 -> 1.5 mA, off at 8 s
        "freq2": np.where(t < 5, 25.0, 30.0),                        # 25 Hz, then 30 Hz
    }
    savemat(OUT / "per_channel_2ch.mat", {
        **{k: v.reshape(-1, 1) for k, v in variables.items()},
        "name": "Two channels, per-channel variables (demo)",
        "description": "t, pw1, a1, freq1, pw2, a2, freq2 in seconds, amps and Hz. Frequency changes over time.",
    }, format="5")
    with open(OUT / "per_channel_2ch.txt", "w", encoding="utf-8") as handle:
        handle.write("% Same data as per_channel_2ch.mat: seconds, amps, Hz\n")
        handle.write("name = Two channels, text file (demo)\n")
        for key, values in variables.items():
            handle.write(f"{key} = " + ", ".join(f"{v:g}" for v in values) + "\n")


if __name__ == "__main__":
    main()
