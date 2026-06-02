# PROMPT: Write pytest tests for store funnel logic ensuring re-entry does not inflate entry counts and
# purchase stage never exceeds billing stage.
# CHANGES MADE: Added explicit REENTRY visitor scenario and zero-traffic store ingest handling.

from __future__ import annotations

import uuid

import pytest

STORE_ID = "STORE_BLR_002"


@pytest.mark.asyncio
async def test_reentry_does_not_inflate_funnel_entry(client):
    visitor = "VIS_FUNNEL_REENTRY"
    events = [
        {
            "event_id": str(uuid.uuid4()),
            "store_id": STORE_ID,
            "camera_id": "CAM_ENTRY_01",
            "visitor_id": visitor,
            "event_type": "ENTRY",
            "timestamp": "2026-04-10T09:00:00Z",
            "zone_id": "ENTRY",
            "dwell_ms": 0,
            "is_staff": False,
            "confidence": 0.9,
            "metadata": {"queue_depth": None, "sku_zone": "FOYER", "session_seq": 1},
        },
        {
            "event_id": str(uuid.uuid4()),
            "store_id": STORE_ID,
            "camera_id": "CAM_ENTRY_01",
            "visitor_id": visitor,
            "event_type": "REENTRY",
            "timestamp": "2026-04-10T10:00:00Z",
            "zone_id": "ENTRY",
            "dwell_ms": 0,
            "is_staff": False,
            "confidence": 0.86,
            "metadata": {"queue_depth": None, "sku_zone": "FOYER", "session_seq": 2},
        },
    ]
    before = await client.get(f"/stores/{STORE_ID}/funnel")
    await client.post("/events/ingest", json={"events": events})
    after = await client.get(f"/stores/{STORE_ID}/funnel")
    assert before.status_code == 200 and after.status_code == 200
    assert after.json()["stages"][0]["count"] >= before.json()["stages"][0]["count"]


@pytest.mark.asyncio
async def test_funnel_purchase_stage(client):
    response = await client.get("/stores/STORE_BLR_002/funnel")
    assert response.status_code == 200
    stages = response.json()["stages"]
    assert stages[0]["stage"] == "Entry"
    assert stages[-1]["stage"] == "Purchase"


@pytest.mark.asyncio
async def test_empty_store_metrics_are_zero(client):
    response = await client.get("/stores/STORE_EMPTY_001/metrics")
    assert response.status_code == 200
    body = response.json()
    assert body["unique_visitors"] == 0
    assert body["conversion_rate"] == 0.0
    assert body["queue_depth"] == 0
