% Example: build a stimulation time series in MATLAB and save it in the
% layout the COSMIIC Stimulation Software imports (docs/MATLAB_IMPORT.md).
% Open the result with "Import Program / MATLAB File" on the Main Menu.

dt = 0.020;                        % fixed time step, seconds (20 ms)
time_s = (0:dt:4)';                % N x 1, seconds from the start

% One column per channel (N x 2 here): amplitude in mA
a1 = min(max(time_s / 2, 0), 1) * 2.5;          % ch1: 0 -> 2.5 mA over 2 s
a2 = min(max((time_s - 1) / 2, 0), 1) * 2.0;    % ch2: starts at 1 s, -> 2 mA
amplitude_ma = [a1, a2];

pulse_width_us = 50;               % one value = same for all channels and times
                                   % (or N x 2 to vary it over time)
frequency_hz = [20, 25];           % one per channel (or a single value)

name = 'Two channel ramp (demo)';
description = 'Ch1 ramps to 2.5 mA, ch2 to 2 mA.';

% '-v7' is the default; '-v7.3' files can't be read yet.
save('ramp_2ch.mat', 'time_s', 'amplitude_ma', 'pulse_width_us', ...
     'frequency_hz', 'name', 'description', '-v7');
