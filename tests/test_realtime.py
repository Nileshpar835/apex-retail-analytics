from __future__ import annotations

from collections import defaultdict

import pytest

from app.realtime import RealtimeAnalyticsService


class FakeRedis:
    def __init__(self) -> None:
        self._sets: dict[str, set[str]] = defaultdict(set)

    async def sadd(self, key: str, member: str) -> None:
        self._sets[key].add(member)

    async def srem(self, key: str, member: str) -> None:
        self._sets[key].discard(member)

    async def scard(self, key: str) -> int:
        return len(self._sets[key])


@pytest.mark.asyncio
async def test_aggregates_core_metrics() -> None:
    service = RealtimeAnalyticsService(FakeRedis(), "data/store_events.jsonl")

    await service._apply_event(
        {
            "visitor_id": "CUST_1",
            "camera_id": "CAM_3",
            "event_type": "ENTRY",
            "zone_id": "ENTRY_EXIT",
            "role": "CUSTOMER",
        }
    )
    await service._apply_event(
        {
            "visitor_id": "CUST_1",
            "camera_id": "CAM_5",
            "event_type": "BILLING_QUEUE_JOIN",
            "zone_id": "checkout_queue",
            "role": "CUSTOMER",
        }
    )
    await service._apply_event(
        {
            "visitor_id": "CUST_2",
            "camera_id": "CAM_1",
            "event_type": "ZONE_ENTER",
            "zone_id": "SKINCARE_LEFT",
            "role": "CUSTOMER",
        }
    )

    metrics = await service.get_metrics()
    assert metrics["active_footfall"] == 1
    assert metrics["queue_length"] == 1
    assert metrics["zone_occupancy"]["CAM_1"] == 1
    assert metrics["zone_occupancy"]["CAM_2"] == 0


def test_enrich_event_adds_visual_fields() -> None:
    service = RealtimeAnalyticsService(FakeRedis(), "data/store_events.jsonl")
    enriched = service._enrich_event({"camera_id": "CAM 4", "zone_id": "BACKROOM", "is_staff": False})
    assert enriched["camera_id"] == "CAM_4"
    assert enriched["zone_id"] == "cam_4_backroom"
    assert enriched["role"] == "CUSTOMER"
    assert 0.0 <= enriched["x"] <= 1.0
    assert 0.0 <= enriched["y"] <= 1.0
