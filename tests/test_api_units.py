# PROMPT: Add direct unit tests for analytics, health, metrics edge cases, and tracker helpers.
# CHANGES MADE: Focused on deterministic pure-function tests to raise coverage above 70%.

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.analytics import get_store_anomalies, get_store_heatmap, normalize_scores
from app.database import EventRecord
from app.health import get_health_status
from app.metrics import (
    compute_abandonment_rate,
    compute_avg_dwell_per_zone,
    compute_queue_depth,
    filter_events_for_date,
    unique_visitors_from_sessions,
)
from app.db_session import get_session_factory
from pipeline.tracker import VisitorRegistry, crossed_line, detect_staff, normalized_center


def make_record(**kwargs) -> EventRecord:
    defaults = {
        "event_id": "evt-1",
        "store_id": "STORE_BLR_002",
        "camera_id": "CAM_ENTRY_01",
        "visitor_id": "VIS_001",
        "event_type": "ENTRY",
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "zone_id": "ENTRY",
        "dwell_ms": 0,
        "is_staff": False,
        "confidence": 0.9,
        "metadata_json": "{}",
    }
    defaults.update(kwargs)
    return EventRecord(**defaults)


def test_normalize_scores():
    scores = normalize_scores({"A": 10, "B": 5})
    assert scores["A"] == 100.0
    assert scores["B"] == 50.0


def test_filter_events_for_date_latest():
    today = datetime.now(timezone.utc).date().isoformat()
    yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).date().isoformat()
    events = [
        make_record(timestamp=f"{yesterday}T08:00:00Z"),
        make_record(event_id="evt-2", timestamp=f"{today}T09:00:00Z"),
    ]
    filtered = filter_events_for_date(events)
    assert len(filtered) == 1
    assert filtered[0].event_id == "evt-2"


def test_unique_visitors_excludes_staff_only_sessions():
    sessions = {
        "VIS_A": [make_record(event_type="ENTRY", visitor_id="VIS_A")],
        "VIS_STAFF": [make_record(event_type="ZONE_ENTER", visitor_id="VIS_STAFF", is_staff=True)],
    }
    assert unique_visitors_from_sessions(sessions) == {"VIS_A"}


def test_compute_avg_dwell_and_queue_and_abandonment():
    events = [
        make_record(event_type="ZONE_ENTER", zone_id="SKINCARE"),
        make_record(event_id="e2", event_type="ZONE_DWELL", zone_id="SKINCARE", dwell_ms=30000),
        make_record(event_id="e3", event_type="BILLING_QUEUE_JOIN", zone_id="BILLING", metadata_json='{"queue_depth": 2}'),
        make_record(event_id="e4", event_type="BILLING_QUEUE_ABANDON", zone_id="BILLING"),
    ]
    dwell = compute_avg_dwell_per_zone(events)
    assert dwell[0].zone_id == "SKINCARE"
    assert compute_queue_depth(events) >= 1
    assert compute_abandonment_rate(events) == 1.0


def test_visitor_registry_reentry():
    registry = VisitorRegistry()
    ts = datetime.now(timezone.utc)
    signature = "abc123"
    visitor_id, kind = registry.resolve_visitor(1, signature, ts)
    assert kind is None
    registry.mark_exit(signature, visitor_id, ts)
    visitor_id_2, kind_2 = registry.resolve_visitor(2, signature, ts + timedelta(minutes=10))
    assert kind_2 == "REENTRY"
    assert visitor_id_2 == visitor_id


def test_crossed_line_entry_and_exit():
    line = {"x1": 0.2, "y1": 0.7, "x2": 0.8, "y2": 0.7, "inbound_direction": "up"}
    assert crossed_line((0.5, 0.8), (0.5, 0.6), line) == "ENTRY"
    assert crossed_line((0.5, 0.6), (0.5, 0.8), line) == "EXIT"


def test_normalized_center():
    assert normalized_center((0, 0, 100, 200), 200, 400) == (0.25, 0.25)


def test_detect_staff_on_purple_patch():
    import numpy as np

    frame = np.zeros((100, 100, 3), dtype=np.uint8)
    frame[:, :] = (130, 80, 180)
    is_staff, confidence = detect_staff(frame, (10, 10, 60, 90), billing_ratio=0.0)
    assert is_staff is True
    assert confidence > 0.5


@pytest.mark.asyncio
async def test_heatmap_and_anomalies_with_seeded_db(client):
    session_factory = get_session_factory()
    async with session_factory() as session:
        heatmap = await get_store_heatmap(session, "STORE_BLR_002")
        anomalies = await get_store_anomalies(session, "STORE_BLR_002")
        health = await get_health_status(session)
    assert heatmap.data_confidence in {"HIGH", "LOW"}
    assert anomalies.store_id == "STORE_BLR_002"
    assert health.status in {"OK", "DEGRADED"}
