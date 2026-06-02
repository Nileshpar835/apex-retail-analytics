# Author: Krish Jagdishkumar Ahir
from __future__ import annotations

import time
from typing import Any

import cv2
import numpy as np
from pipeline.staff_classifier import is_black_outfit

DEFAULT_CAMERA_POLYGONS: dict[str, dict[str, list[tuple[float, float]]]] = {
    "CAM 1": {
        "SKINCARE_LEFT": [(0.0, 0.0), (0.5, 0.0), (0.5, 1.0), (0.0, 1.0)],
    },
    "CAM 2": {
        "MAKEUP": [(0.5, 0.0), (1.0, 0.0), (1.0, 0.5), (0.5, 0.5)],
        "FRAGRANCE": [(0.5, 0.5), (1.0, 0.5), (1.0, 1.0), (0.5, 1.0)],
    },
    "CAM 3": {
        "ENTRY_EXIT": [(0.2, 0.6), (0.8, 0.6), (0.8, 1.0), (0.2, 1.0)],
    },
    "CAM 4": {
        "BACKROOM": [(0.1, 0.1), (0.9, 0.1), (0.9, 0.9), (0.1, 0.9)],
    },
    "CAM 5": {
        "CHECKOUT": [(0.15, 0.2), (0.85, 0.2), (0.85, 0.85), (0.15, 0.85)],
    },
}


class VisionEngine:
    """Core CV engine with person tracking, staff classification, and zone assignment."""

    def __init__(
        self,
        *,
        model_name: str = "yolov8n.pt",
        tracker: str = "botsort.yaml",
        confidence: float = 0.25,
        iou: float = 0.5,
        camera_polygons: dict[str, dict[str, list[tuple[float, float]]]] | None = None,
        model: Any | None = None,
    ) -> None:
        self.tracker = tracker
        self.confidence = confidence
        self.iou = iou
        self.camera_polygons = camera_polygons or DEFAULT_CAMERA_POLYGONS
        self._frame_id = 0
        if model is not None:
            self.model = model
        else:
            from ultralytics import YOLO

            self.model = YOLO(model_name)

    def classify_staff(self, frame: np.ndarray, bbox: tuple[float, float, float, float]) -> str:
        """
        Classify as STAFF when both upper and lower body are predominantly dark.
        """
        x1, y1, x2, y2 = map(int, bbox)
        frame_h, frame_w = frame.shape[:2]
        x1, y1 = max(0, x1), max(0, y1)
        x2, y2 = min(frame_w, x2), min(frame_h, y2)
        if x2 <= x1 or y2 <= y1:
            return "CUSTOMER"

        crop = frame[y1:y2, x1:x2]
        if crop.size == 0:
            return "CUSTOMER"

        is_staff, _ = is_black_outfit(frame, (x1, y1, x2, y2))
        return "STAFF" if is_staff else "CUSTOMER"

    def _resolve_zone(self, camera: str, feet: tuple[float, float], frame_shape: tuple[int, ...]) -> str:
        camera_zones = self.camera_polygons.get(camera, {})
        if not camera_zones:
            return "UNKNOWN"

        frame_h, frame_w = frame_shape[:2]
        for zone_name, polygon in camera_zones.items():
            pixel_polygon = np.array(
                [(px * frame_w, py * frame_h) for px, py in polygon],
                dtype=np.float32,
            )
            if cv2.pointPolygonTest(pixel_polygon, feet, False) >= 0:
                return zone_name
        return "UNKNOWN"

    def process_frame(
        self,
        frame: np.ndarray,
        *,
        camera: str,
        timestamp: float | None = None,
    ) -> list[dict[str, int | float | str]]:
        """
        Track persons, classify role, assign zone using feet point, and emit normalized detections.
        """
        frame_id = self._frame_id
        self._frame_id += 1
        event_time = float(time.time() if timestamp is None else timestamp)

        results = self.model.track(
            frame,
            persist=True,
            tracker=self.tracker,
            classes=[0],
            conf=self.confidence,
            iou=self.iou,
            verbose=False,
        )

        detections: list[dict[str, int | float | str]] = []
        if not results:
            return detections
        boxes = getattr(results[0], "boxes", None)
        if boxes is None:
            return detections

        for box in boxes:
            if box.id is None:
                continue
            x1, y1, x2, y2 = box.xyxy[0].tolist()
            track_id = int(box.id[0])
            feet = (float((x1 + x2) / 2.0), float(y2))
            role = self.classify_staff(frame, (x1, y1, x2, y2))
            zone = self._resolve_zone(camera, feet, frame.shape)
            detections.append(
                {
                    "frame_id": frame_id,
                    "track_id": track_id,
                    "role": role,
                    "camera": camera,
                    "zone": zone,
                    "timestamp": event_time,
                }
            )
        return detections
