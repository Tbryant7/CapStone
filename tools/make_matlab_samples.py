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
    print(f"Wrote samples to {OUT}")


if __name__ == "__main__":
    main()
