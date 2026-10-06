# Joint-angle overlay

[← Back to README](../README.md)

The right-hand translucent dashboard matches cyan knee, violet hip and amber
ankle arcs on the selected leg. Arcs span the interior angle between the two
segment directions. At the ankle, the heel-to-toe foot axis is translated to
the ankle center for drawing.
Values update every frame; unavailable measurements show `--`. By default the
most visible measurable side is selected on the first suitable frame and locked
for the video. Use `--side left` or `--side right` to override. JSON schema v3
stores both sides under each frame's `angles`, in degrees, with unavailable
angles represented by `null` (never stale values).

- **Knee angle:** `angle(hip-knee, ankle-knee)`; a straight knee is 180°.
- **Hip angle:** `angle(shoulder-hip, knee-hip)`; a straight trunk/thigh
  is 180°. This is a trunk-thigh proxy, not an isolated measurement of pelvic tilt
  or the anatomical pelvis-femur angle.
- **Ankle angle:** `angle(knee-ankle, toe-heel)`; a shin perpendicular
  to the heel-to-toe foot axis is 90°. The angle decreases as the shin leans
  toward the toes during descent. The foot axis avoids the ankle-to-toe
  downward slope in neutral stance.

All three angles are interior angles in [0°, 180°] and decrease with squat
flexion. Schema v3 uses `knee_angle_deg`, `hip_angle_deg`, `ankle_angle_deg`;
these replace the v2 flexion/dorsiflexion fields, which used a different convention.

All vectors use pixel-scaled x/y to correct for image aspect ratio. These are
2D side-view estimates; camera perspective and landmark errors affect accuracy.
No clinical calibration or initial-pose zeroing is performed. Hip/knee magnitudes
do not distinguish hyperextension. Displayed integers round the full-precision
values stored in JSON. The dashboard sits in the right margin; frame subjects
to its left to keep the overlay clear.
