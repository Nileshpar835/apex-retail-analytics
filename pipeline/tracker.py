from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone


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
    line_y = (y1 + y2) / 2
    direction = line.get("inbound_direction", "up")
    crossed = (px >= line_y and cy < line_y) or (px <= line_y and cy > line_y) if x1 != x2 else False
    if abs(py - line_y) <= 0.02 or abs(cy - line_y) <= 0.02:
        crossed = True
    if not crossed:
        if direction == "up" and py >= line_y > cy:
            return "ENTRY"
        if direction == "up" and py <= line_y < cy:
            return "EXIT"
        if direction == "down" and py <= line_y < cy:
            return "ENTRY"
        if direction == "down" and py >= line_y > cy:
            return "EXIT"
    else:
        if direction == "up":
            return "ENTRY" if cy < py else "EXIT"
        return "ENTRY" if cy > py else "EXIT"
    return None


@dataclass
class TrackState:
    track_id: int
    visitor_id: str
    is_staff: bool = False
    active: bool = True
    exited: bool = False
    last_center: tuple[float, float] | None = None
    current_zones: set[str] = field(default_factory=set)
    zone_enter_frame: dict[str, int] = field(default_factory=dict)
    last_dwell_emit: dict[str, int] = field(default_factory=dict)
    billing_joined: bool = False
    session_started: bool = False
    appearance_hash: str = ""


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
    purple_mask = cv2.inRange(hsv, np.array([125, 40, 40]), np.array([165, 255, 255]))
    purple_ratio = float(purple_mask.mean()) / 255.0
    if purple_ratio > 0.18 or billing_ratio > 0.75:
        confidence = min(0.95, 0.55 + purple_ratio)
        return True, confidence
    return False, 0.65
