from __future__ import annotations

import numpy as np

from pipeline.vision_engine import VisionEngine


class _FakeBox:
    def __init__(self, bbox: tuple[float, float, float, float], track_id: int) -> None:
        self.xyxy = np.array([bbox], dtype=float)
        self.id = np.array([track_id], dtype=int)


class _FakeResult:
    def __init__(self, boxes: list[_FakeBox]) -> None:
        self.boxes = boxes


class _FakeModel:
    def __init__(self, boxes: list[_FakeBox]) -> None:
        self._boxes = boxes
        self.last_track_kwargs: dict[str, object] = {}

    def track(self, frame, **kwargs):  # noqa: ANN001
        self.last_track_kwargs = kwargs
        return [_FakeResult(self._boxes)]


def test_classify_staff_uses_dark_ratio_in_lower_70_percent():
    frame = np.full((120, 120, 3), 255, dtype=np.uint8)
    x1, y1, x2, y2 = 20, 20, 100, 100
    lower_70_start = y1 + int((y2 - y1) * 0.3)
    frame[lower_70_start:y2, x1:x2] = 0

    engine = VisionEngine(model=_FakeModel([]))
    assert engine.classify_staff(frame, (x1, y1, x2, y2)) == "STAFF"


def test_process_frame_tracks_people_only_and_assigns_zone():
    frame = np.full((100, 100, 3), 255, dtype=np.uint8)
    fake_model = _FakeModel([_FakeBox((10, 10, 40, 90), 7)])
    engine = VisionEngine(model=fake_model)

    detections = engine.process_frame(frame, camera="CAM 1", timestamp=123.4)

    assert len(detections) == 1
    detection = detections[0]
    assert detection == {
        "frame_id": 0,
        "track_id": 7,
        "role": "CUSTOMER",
        "camera": "CAM 1",
        "zone": "SKINCARE_LEFT",
        "timestamp": 123.4,
    }
    assert fake_model.last_track_kwargs["classes"] == [0]
    assert fake_model.last_track_kwargs["tracker"] == "botsort.yaml"


def test_process_frame_returns_unknown_zone_when_feet_outside_polygons():
    frame = np.full((100, 100, 3), 255, dtype=np.uint8)
    fake_model = _FakeModel([_FakeBox((5, 5, 20, 20), 3)])
    engine = VisionEngine(model=fake_model)

    detections = engine.process_frame(frame, camera="CAM 2", timestamp=50.0)

    assert detections[0]["zone"] == "UNKNOWN"
