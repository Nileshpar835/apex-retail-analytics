from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from collections import deque
from datetime import datetime, timedelta, timezone

EPSILON = 1e-6
TRACK_CENTERS_WINDOW = 6


def point_in_polygon(x: float, y: float, polygon: list[list[float]]) -> bool:
    inside = False
    j = len(polygon) - 1
    for i in range(len(polygon)):
        xi, yi = polygon[i]
        xj, yj = polygon[j]
        intersects = ((yi > y) != (yj > y)) and (x < (xj - xi) * (y - yi) / ((yj - yi) or 1e-9) + xi)
        if intersects:
            inside = not inside
        j = i
    return inside


def normalized_center(bbox: tuple[float, float, float, float], width: int, height: int) -> tuple[float, float]:
    x1, y1, x2, y2 = bbox
    return ((x1 + x2) / 2) / width, ((y1 + y2) / 2) / height


def crossed_line(
    prev_center: tuple[float, float] | None,
    center: tuple[float, float],
    line: dict,
) -> str | None:
    if prev_center is None:
        return None
    x1, y1, x2, y2 = line["x1"], line["y1"], line["x2"], line["y2"]
    px, py = prev_center
    cx, cy = center
    line_vec_x, line_vec_y = x2 - x1, y2 - y1

    prev_side = line_vec_x * (py - y1) - line_vec_y * (px - x1)
    curr_side = line_vec_x * (cy - y1) - line_vec_y * (cx - x1)
    if abs(prev_side) < EPSILON or abs(curr_side) < EPSILON:
        return None
    if prev_side * curr_side > 0:
        return None

    move_x, move_y = cx - px, cy - py
    movement_cross = line_vec_x * move_y - line_vec_y * move_x
    if abs(movement_cross) < EPSILON:
        return None

    direction = line.get("inbound_direction", "up")
    in_on_negative_cross = direction in {"up", "left"}
    moving_inside = movement_cross < 0 if in_on_negative_cross else movement_cross > 0
    return "IN" if moving_inside else "OUT"


@dataclass
class TrackState:
    track_id: int
    visitor_id: str
    is_staff: bool = False
    active: bool = True
    exited: bool = False
    last_center: tuple[float, float] | None = None
    current_zones: set[str] = field(default_factory=set)
    zone_entry_time: dict[str, datetime] = field(default_factory=dict)
    billing_joined: bool = False
    session_started: bool = False
    appearance_hash: str = ""
    last_seen_frame: int = -1
    crossing_counted: bool = False
    centers: deque[tuple[float, float]] = field(default_factory=lambda: deque(maxlen=TRACK_CENTERS_WINDOW))
    pending_reentry: bool = False


@dataclass
class VisitorRegistry:
    next_id: int = 1
    exited_signatures: dict[str, tuple[str, datetime]] = field(default_factory=dict)
    staff_track_ids: set[int] = field(default_factory=set)

    def new_visitor_id(self) -> str:
        visitor = f"VIS_{self.next_id:06d}"
        self.next_id += 1
        return visitor

    def signature(self, bbox: tuple[float, float, float, float], frame: object | None = None) -> str:
        x1, y1, x2, y2 = bbox
        h = y2 - y1
        w = x2 - x1
        color_hint = ""
        if frame is not None:
            import numpy as np

            arr = np.asarray(frame)
            y_mid = int((y1 + y2) / 2)
            x_mid = int((x1 + x2) / 2)
            if 0 <= y_mid < arr.shape[0] and 0 <= x_mid < arr.shape[1]:
                patch = arr[max(0, y_mid - 5) : y_mid + 5, max(0, x_mid - 5) : x_mid + 5]
                if patch.size:
                    color_hint = str(tuple(int(v) for v in patch.mean(axis=(0, 1))[:3]))
        raw = f"{round(w)}:{round(h)}:{color_hint}"
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:10]

    def resolve_visitor(
        self,
        track_id: int,
        signature: str,
        timestamp: datetime,
        *,
        is_staff: bool = False,
    ) -> tuple[str, str | None]:
        if is_staff:
            self.staff_track_ids.add(track_id)
            return self.new_visitor_id(), None

        if signature in self.exited_signatures:
            prior_visitor, exit_time = self.exited_signatures[signature]
            if timestamp - exit_time <= timedelta(minutes=45):
                del self.exited_signatures[signature]
                return prior_visitor, "REENTRY"
        return self.new_visitor_id(), None

    def mark_exit(self, signature: str, visitor_id: str, timestamp: datetime) -> None:
        self.exited_signatures[signature] = (visitor_id, timestamp)


def detect_staff(frame, bbox: tuple[float, float, float, float], billing_ratio: float) -> tuple[bool, float]:
    import cv2
    import numpy as np

    x1, y1, x2, y2 = map(int, bbox)
    h, w = frame.shape[:2]
    x1, y1 = max(0, x1), max(0, y1)
    x2, y2 = min(w, x2), min(h, y2)
    if x2 <= x1 or y2 <= y1:
        return False, 0.5

    crop = frame[y1:y2, x1:x2]
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    dark_mask = (hsv[:, :, 2] < 75) & (hsv[:, :, 1] < 70)
    dark_ratio = float(np.mean(dark_mask))
    split_index = dark_mask.shape[0] // 2
    upper_dark_ratio = float(np.mean(dark_mask[:split_index, :])) if split_index > 0 else 0.0
    lower_dark_ratio = float(np.mean(dark_mask[split_index:, :])) if split_index < dark_mask.shape[0] else 0.0

    upper_threshold = 0.45 if billing_ratio < 0.5 else 0.42
    lower_threshold = 0.45 if billing_ratio < 0.5 else 0.42
    overall_threshold = 0.42 if billing_ratio < 0.5 else 0.38

    is_staff = (
        upper_dark_ratio >= upper_threshold
        and lower_dark_ratio >= lower_threshold
        and dark_ratio >= overall_threshold
    )
    if is_staff:
        confidence = min(0.95, 0.55 + ((upper_dark_ratio + lower_dark_ratio + dark_ratio) / 3.0) * 0.4)
        return True, confidence
    confidence = max(0.35, min(0.8, 0.7 - ((upper_dark_ratio + lower_dark_ratio + dark_ratio) / 3.0) * 0.3))
    return False, confidence
