# Technique notes and height calibration

[← Back to README](../README.md)

![Technique notes](assets/technique-notes.png)

## Geometry-based side-view technique notes

Both portable dashboards include per-session counts and expandable per-repetition
notes for a minimum knee angle of 90 degrees or less, hip/shoulder coordination during early
ascent, and estimated heel lift. Selecting or editing a repetition recomputes the
notes immediately; evidence buttons seek the relevant video frame. The technique
JSON download includes current boundaries, thresholds, results and calibration.

`technique.py` prepares fixed-side, confidence-gated image-pixel trajectories.
Visibility and presence must both be at least 0.65. Coordinates are smoothed with
a 0.2-second Savitzky–Golay window without interpolating occlusions. `technique.js`
contains pure geometric rules independent of MediaPipe and the browser UI.
`technique_ui.js` handles presentation and optional calibration. No learned
exercise-quality classifier is used; the previous external-model experiment,
weights and isolated experiment environment have been removed. MediaPipe remains
the landmark extractor.

### Rules

**Depth** uses the minimum reliable interior knee angle across the entire repetition:
90 degrees or less meets the project target; greater than 90 does not. It uses
the original aspect-corrected angle measurements with an additional 0.65
visibility/presence gate on hip, knee and ankle. At least 80% coverage is required
both across the repetition and around the marked bottom. This is a project
criterion, not a competition-depth decision.

**Coordination** flags simultaneous hip-first rise
over 8% of bottom torso length and trunk-inclination increase of at least 12°,
maintained for 0.15 seconds in the first half of ascent.

**Heel lift** requires a
relative heel/toe vertical change over 6% of projected foot length and a foot
angle increase of at least 8°, maintained for 0.15 seconds. The reference is the
start of that repetition, assuming an initially planted heel.

At least 80% valid
coverage is needed per assessment window; insufficient resolution, missing
landmarks or substantial toe motion yield `unavailable`, never a clean result.
The heel rule uses only the selected near foot, never both feet or a fallback
to the far foot. The default foot is selected once per video using heel/toe
visibility; the user can explicitly select anatomical left/right because
visibility alone does not prove which foot is nearer. This choice is independent
of the fixed torso/knee measurement side. Thresholds are experimental heuristics,
not validated clinical limits.

## Height calibration

User height is entered in centimetres. `calibration.js` automatically estimates
pixel stature using the selected near side within ±0.1 seconds of the first rep's
start: vertical floor-to-ankle height + ankle-to-knee + knee-to-hip + hip-to-shoulder
+ shoulder-to-ear Euclidean lengths. Floor Y is approximated by the lower heel/toe
landmark. Calibration uses raw confidence-gated pixel landmarks, with median
segment lengths over at least three valid upright frames (knee >=160°, hip >=150°).
All points must be visible and in the expected vertical order; a total-length
range exceeding 12% of its median makes the automatic estimate unavailable.
An editable **experimental 6% allowance** of the measured sum approximates the
missing ear-to-crown segment. This coefficient is not an anthropometric guarantee.
Height / estimated total pixels gives cm/pixel, automatically when a valid height
is entered. It does not correct perspective, camera tilt or out-of-plane motion.

The user can view the reference image with segment overlays and edit the five
lengths and head allowance (0–20%). Manual lengths are tied to start frame and
side, and reset when either changes. Invalid/insufficient data disables automatic
scale rather than keeping a stale one; complete manual lengths can supply an
explicit fallback. Reset restores automatic lengths and the 6% head allowance.
Old crown/floor calibration is not silently reused; valid saved user height and
foot selection are retained. The export identifies automatic/manual mode, window,
segments, coefficient, reference frame and scale.

The scale adds approximate centimetres to technique-note distances; existing
velocity plots retain their explicitly labeled px/s units. No height or physical
scale is invented for the demo videos. Rules use dimensionless ratios and angles
and therefore remain available without physical calibration. Calibration and
near-foot selection persist per analysis in local browser storage and can be exported.
