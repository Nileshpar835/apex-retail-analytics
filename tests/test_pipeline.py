# PROMPT: Generate pipeline unit tests for event schema validation and polygon zone checks.
# CHANGES MADE: Added direct tests for EventEmitter and point_in_polygon helper used by tracker.py.

from __future__ import annotations

from pipeline.emit import EventEmitter
from pipeline.tracker import point_in_polygon


def test_event_emitter_schema_fields():
    emitter = EventEmitter(
        store_id="STORE_BLR_002",
        camera_id="CAM_ENTRY_01",
        clip_start_utc="2026-04-10T06:30:00Z",
    )
    event = emitter.emit(
        visitor_id="VIS_000001",
        event_type="ENTRY",
        frame_index=30,
        fps=30.0,
        zone_id="ENTRY",
        confidence=0.77,
        metadata={"sku_zone": "FOYER"},
    )
    assert event["event_type"] == "ENTRY"
    assert event["store_id"] == "STORE_BLR_002"
    assert event["metadata"]["session_seq"] == 1
    assert event["confidence"] == 0.77


def test_point_in_polygon():
    polygon = [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]]
    assert point_in_polygon(0.5, 0.5, polygon)
    assert not point_in_polygon(1.5, 0.5, polygon)


def test_event_emitter_write_jsonl(tmp_path):
    emitter = EventEmitter(
        store_id="STORE_BLR_002",
        camera_id="CAM_ENTRY_01",
        clip_start_utc="2026-04-10T06:30:00Z",
    )
    events = [
        emitter.emit(
            visitor_id="VIS_000001",
            event_type="ENTRY",
            frame_index=10,
            fps=30.0,
            zone_id="ENTRY",
        )
    ]
    out = tmp_path / "events.jsonl"
    EventEmitter.write_jsonl(events, str(out))
    assert out.read_text(encoding="utf-8").strip().startswith("{")
