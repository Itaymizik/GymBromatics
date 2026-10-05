"""OpenCV skeleton drawing, independent of MediaPipe."""

import cv2
import numpy as np

from .state import FrameState, LANDMARK_NAMES
from .squat_logic import FrameAngles, JOINTS, joint_vectors

# Anatomical connections in the shared 33-point landmark schema.
_CONNECTION_IDS = (
    (0, 1), (1, 2), (2, 3), (3, 7), (0, 4), (4, 5), (5, 6), (6, 8), (9, 10),
    (11, 12), (11, 13), (13, 15), (15, 17), (15, 19), (15, 21), (17, 19),
    (12, 14), (14, 16), (16, 18), (16, 20), (16, 22), (18, 20),
    (11, 23), (12, 24), (23, 24), (23, 25), (24, 26), (25, 27), (26, 28),
    (27, 29), (28, 30), (29, 31), (30, 32), (27, 31), (28, 32),
)
CONNECTIONS = tuple((LANDMARK_NAMES[a], LANDMARK_NAMES[b]) for a, b in _CONNECTION_IDS)


class SkeletonVisualizer:
    def __init__(self, confidence: float = 0.5) -> None:
        if not 0.0 <= confidence <= 1.0:
            raise ValueError("Confidence must be between 0 and 1")
        self.confidence = confidence

    def draw(self, frame: np.ndarray, state: FrameState, angles: FrameAngles | None = None) -> np.ndarray:
        output = frame.copy()
        height, width = frame.shape[:2]
        points = {
            name: (round(point.x * (width - 1)), round(point.y * (height - 1)))
            for name, point in state.landmarks.items()
            if point.is_reliable(self.confidence)
            and 0.0 <= point.x <= 1.0 and 0.0 <= point.y <= 1.0
        }
        thickness = max(2, round(min(width, height) / 300))
        for start, end in CONNECTIONS:
            if start in points and end in points:
                cv2.line(output, points[start], points[end], (60, 230, 80), thickness, cv2.LINE_AA)
        for point in points.values():
            cv2.circle(output, point, thickness + 2, (20, 20, 20), -1, cv2.LINE_AA)
            cv2.circle(output, point, thickness, (0, 210, 255), -1, cv2.LINE_AA)
        return output


# BGR colors: cyan knee, violet hip, amber ankle.
ANGLE_COLORS = ((245, 210, 70), (240, 140, 205), (75, 190, 255))


class AngleVisualizer(SkeletonVisualizer):
    """Joint arcs plus a compact translucent dashboard in the right margin."""

    def draw(self, frame: np.ndarray, state: FrameState, angles: FrameAngles | None = None) -> np.ndarray:
        output = super().draw(frame, state)
        if angles is None:
            return output
        height, width = output.shape[:2]
        scale = min(width / 640, height / 360)
        if angles.display_side:
            for joint, value, color in zip(JOINTS, angles.selected.values(), ANGLE_COLORS):
                geometry = joint_vectors(state, angles.display_side, joint, width, height, self.confidence)
                if value is None or geometry is None:
                    continue
                center, upper, lower = geometry
                reference, moving = upper, lower
                radius = max(5, min(24 * scale, np.linalg.norm(upper) * .35, np.linalg.norm(lower) * .7))
                origin = tuple(np.rint(center).astype(int))
                # Bound the interior angle by its actual segment directions.
                # At the ankle, translate the heel-to-toe axis to the joint center.
                for segment in (reference, moving):
                    endpoint = tuple(np.rint(center + segment / np.linalg.norm(segment) * radius).astype(int))
                    cv2.line(output, origin, endpoint, color, max(1, round(scale)), cv2.LINE_AA)
                start_angle = np.arctan2(reference[1], reference[0])
                end_angle = np.arctan2(moving[1], moving[0])
                sweep = (end_angle - start_angle + np.pi) % (2 * np.pi) - np.pi
                samples = np.linspace(start_angle, start_angle + sweep, 40)
                arc = np.rint(center + radius * np.column_stack((np.cos(samples), np.sin(samples)))).astype(np.int32)
                cv2.polylines(output, [arc], False, (20, 20, 25), max(3, round(4 * scale)), cv2.LINE_AA)
                cv2.polylines(output, [arc], False, color, max(1, round(2 * scale)), cv2.LINE_AA)
                cv2.circle(output, origin, max(3, round(5 * scale)), color, 1, cv2.LINE_AA)
                # Short colored leader and a small matching tag, away from the limb.
                offset = np.array([-64, -7] if joint == "knee" else [32, -12]) * scale
                label = np.rint(center + offset).astype(int)
                label[0] = np.clip(label[0], 4, max(4, width - 64 * scale))
                label[1] = np.clip(label[1], 18 * scale, height - 8 * scale)
                x, y = label
                cv2.line(output, origin, (int(x), int(y)), color, 1, cv2.LINE_AA)
                text = f"{value:.0f}"
                font_scale = .43 * scale
                text_width = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, font_scale, 1)[0][0]
                cv2.rectangle(output, (x - 4, y - round(14 * scale)), (x + text_width + round(12 * scale), y + round(4 * scale)), (28, 24, 20), -1)
                cv2.putText(output, text, (x, y), cv2.FONT_HERSHEY_SIMPLEX, font_scale, color, max(1, round(scale)), cv2.LINE_AA)
                cv2.circle(output, (x + text_width + round(5 * scale), y - round(9 * scale)), max(1, round(2 * scale)), color, 1, cv2.LINE_AA)
        self._dashboard(output, angles, state.timestamp_ms, scale)
        return output

    @staticmethod
    def _dashboard(output: np.ndarray, angles: FrameAngles, timestamp_ms: int, scale: float) -> None:
        # Draw at 2x the design resolution for clean small typography and corners.
        panel = np.zeros((592, 408, 3), dtype=np.uint8)
        panel[:] = (29, 23, 18)

        def text(value: str, x: int, y: int, size: float, color: tuple[int, int, int], thickness: int = 1) -> None:
            cv2.putText(panel, value, (x * 2, y * 2), cv2.FONT_HERSHEY_SIMPLEX, size * 2, color, thickness * 2, cv2.LINE_AA)

        muted = (166, 158, 147)
        white = (246, 243, 237)
        text("SQUAT / JOINT ANGLES", 14, 23, .40, white)
        side = angles.display_side.upper() if angles.display_side else "SEARCHING"
        text(f"{side} SIDE   /   {timestamp_ms / 1000:04.1f}s", 14, 42, .31, muted)
        cv2.line(panel, (28, 104), (380, 104), (69, 58, 46), 2)
        labels = (("KNEE", "shin / thigh"), ("HIP", "thigh / trunk"), ("ANKLE", "shin / foot"))
        for index, ((title, subtitle), value, color) in enumerate(zip(labels, angles.selected.values(), ANGLE_COLORS)):
            top = 63 + index * 68
            cv2.rectangle(panel, (20, top * 2), (388, (top + 59) * 2), (43, 34, 27), -1)
            cv2.rectangle(panel, (20, top * 2), (25, (top + 59) * 2), color, -1)
            text(title, 19, top + 20, .38, color)
            text(subtitle, 19, top + 39, .25, muted)
            label = "--" if value is None else f"{value:.0f}"
            size = .88
            text_width = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, size * 2, 2)[0][0] / 2
            text(label, round(175 - text_width), top + 39, size, white)
            if value is not None:
                cv2.circle(panel, (363, (top + 17) * 2), 5, color, 2, cv2.LINE_AA)
            else:
                text("not visible", 137, top + 52, .20, muted)
        text("STANDING: 180 / 180 / 90", 14, 277, .29, muted)
        text("2D SIDE-VIEW ESTIMATE", 14, 290, .24, muted)
        pw, ph = max(1, round(204 * scale)), max(1, round(296 * scale))
        panel = cv2.resize(panel, (pw, ph), interpolation=cv2.INTER_AREA)
        x, y = output.shape[1] - pw - round(14 * scale), round(18 * scale)
        mask = np.zeros((ph, pw), dtype=np.uint8)
        radius = max(1, round(10 * scale))
        cv2.rectangle(mask, (radius, 0), (pw - radius - 1, ph - 1), 255, -1)
        cv2.rectangle(mask, (0, radius), (pw - 1, ph - radius - 1), 255, -1)
        for cx, cy in ((radius, radius), (pw - radius - 1, radius), (radius, ph - radius - 1), (pw - radius - 1, ph - radius - 1)):
            cv2.circle(mask, (cx, cy), radius, 255, -1, cv2.LINE_AA)
        region = output[y:y + ph, x:x + pw]
        alpha = mask[:, :, None].astype(float) / 255 * .95
        region[:] = np.rint(region * (1 - alpha) + panel * alpha).astype(np.uint8)
