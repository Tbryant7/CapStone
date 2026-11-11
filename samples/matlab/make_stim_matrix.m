% Example: the "stim matrix" layout (docs/MATLAB_IMPORT.md).
% Choose the total time, the number of active channels and the time step,
% then fill one matrix:
%   rows    = total_time_s / time step + 1      (t = 0, dt, 2*dt, ..., total)
%   columns = num_channels * parameters per channel
% Open the result with "Import Program / MATLAB File" on the Main Menu.

total_time_s = 3;                  % 1) total time length, seconds
num_channels = 3;                  % 2) number of active channels
time_step_ms = 20;                 % 3) time step, ms (optional: worked out
                                   %    from total_time_s and the rows if left out)

dt = time_step_ms / 1000;
t = (0:dt:total_time_s)';          % (total_time_s / dt + 1) x 1
rows = numel(t);

% Two parameters per channel, in this order: pulse width (us), amplitude (mA).
% Columns: [ch1_pw, ch1_amp, ch2_pw, ch2_amp, ch3_pw, ch3_amp]
stim = zeros(rows, num_channels * 2);
for ch = 1:num_channels
    start = (ch - 1) * 0.5;                              % each channel starts 0.5 s later
    stim(:, 2*ch - 1) = 50;                              % pulse width, us
    stim(:, 2*ch)     = min(max((t - start) / 1.5, 0), 1) * 2.0;   % ramp to 2 mA over 1.5 s
end

% Anything not in stim is one value (or one per channel):
frequency_hz = 20;

% Optional:
%   parameters = {'pulse_width_us', 'amplitude_ma'};   % column order (this is the default for 2)
%   channels = [1 2 3];                                % channel numbers (default 1..num_channels)
name = 'Three channel stim matrix (demo)';
description = 'Rows = total time / time step + 1, columns = channels x (pw, amp).';

save('stim_matrix_3ch.mat', 'stim', 'total_time_s', 'num_channels', 'time_step_ms', ...
     'frequency_hz', 'name', 'description', '-v7');
