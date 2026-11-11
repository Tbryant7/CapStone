% Example: one variable per channel and parameter (docs/MATLAB_IMPORT.md).
%   t       time, seconds from the start (one fixed step apart)
%   pwN     pulse width of channel N, seconds
%   aN      amplitude of channel N, amps
%   freqN   frequency of channel N, Hz
% Each is one value per time step, or a single value if it doesn't change.
% Frequency may change over time too.
% Open the result with "Import Program / MATLAB File" on the Main Menu.
% (Values in us and mA instead? Add:  units = 'us_mA';  and save it too.)

dt = 0.020;                                   % time step, s
t = (0:dt:10)';                               % 10 s -> 501 rows
env = min(min(t / 2, 1), min((10 - t) / 2, 1));   % ramp up 2 s, hold, ramp down 2 s

pw1 = 0.0001 * (0.5 + 0.5 * env);             % 50 -> 100 us
a1 = 0.002 * env;                             % 0 -> 2 mA
freq1 = 20 + 10 * env;                        % 20 -> 30 Hz

pw2 = 0.00005;                                % 50 us the whole time
a2 = 0.0015 * min(max((t - 1) / 3, 0), 1) .* (t < 8);   % 0 -> 1.5 mA, off at 8 s
freq2 = 25 + 5 * (t >= 5);                    % 25 Hz, then 30 Hz

name = 'Two channels, per-channel variables (demo)';
save('per_channel_2ch.mat', 't', 'pw1', 'a1', 'freq1', 'pw2', 'a2', 'freq2', 'name', '-v7');

% The same thing as a text file, one variable per line:
f = fopen('per_channel_2ch.txt', 'w');
vars = {'t', t; 'pw1', pw1; 'a1', a1; 'freq1', freq1; 'pw2', pw2; 'a2', a2; 'freq2', freq2};
for k = 1:size(vars, 1)
    fprintf(f, '%s = %s\n', vars{k, 1}, strjoin(compose('%g', vars{k, 2}(:)'), ', '));
end
fclose(f);
