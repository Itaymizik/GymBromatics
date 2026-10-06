# Stored repetition comparisons

[← Back to README](../README.md)

Each generated `*_dashboard.json` session and embedded HTML payload includes
`repetition_comparisons` (schema version 1), without adding dashboard UI.
The same field is recomputed for the current boundaries in full-session downloads,
repetition exports and browser storage when repetitions are edited. Imported
comparisons are ignored and recomputed from the session samples. Browser edits
do not overwrite the original JSON file on disk; download to persist those edits.

## Metrics

Total/descent/ascent durations, minimum knee/hip/ankle interior angles,
bottom pause, and peak/mean upward chest-proxy velocity. Phase durations include
any stationary portion assigned by the bottom marker. Velocities remain px/s,
independent of optional height calibration, and are only compared within a session.
Mean velocity is a signed trapezoidal mean over valid adjacent ascent intervals.
Pause uses the existing summary-table definition (deepest 5% of hip excursion,
at most 10% of peak absolute hip speed, continuous for at least 0.2 seconds).

## References and deltas

For each rep, comparisons use the immediately preceding rep and the session
median of available values (including the current rep). Deltas mean current minus
reference. Angles use degree differences only; time/velocity also have percentage
changes, unless the absolute reference is at most 0.01 s / 0.1 px/s. Null results
have reasons. Extrema and pause require complete finite coverage; mean velocity
requires at least 80% valid adjacent intervals. Coverage and the fraction of
interpolated ascent samples are retained; coverage is not a confidence score.
Original boundary provenance and `needs_review` are retained, not interpreted as
confirmation that the repetition boundaries are correct.

## Session trends

Session trends include first-to-last available differences and a least-squares
slope against original repetition ordinals, with at least three available reps
required for a slope. Missing reps are not renumbered. A single rep has no usable
comparison. These are descriptive measurements, without automatic claims of
fatigue, technique quality, or statistically significant change; a session median
is not a technique target.
