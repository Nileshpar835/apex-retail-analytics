"""Example assertions referenced by the challenge statement."""

from __future__ import annotations

import httpx


API_URL = "http://localhost:8000"
STORE_ID = "STORE_BLR_002"


def assert_metrics_valid() -> None:
    response = httpx.get(f"{API_URL}/stores/{STORE_ID}/metrics", timeout=10.0)
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["store_id"] == STORE_ID
    assert payload["unique_visitors"] >= 0
    assert 0.0 <= payload["conversion_rate"] <= 1.0
    assert isinstance(payload["avg_dwell_per_zone"], list)


def assert_funnel_monotonic() -> None:
    response = httpx.get(f"{API_URL}/stores/{STORE_ID}/funnel", timeout=10.0)
    assert response.status_code == 200, response.text
    stages = response.json()["stages"]
    counts = [stage["count"] for stage in stages]
    assert counts[0] >= counts[1] >= counts[2] >= counts[3]


def assert_ingest_idempotent(sample_event: dict) -> None:
    payload = {"events": [sample_event]}
    first = httpx.post(f"{API_URL}/events/ingest", json=payload, timeout=10.0)
    second = httpx.post(f"{API_URL}/events/ingest", json=payload, timeout=10.0)
    assert first.status_code == 200 and second.status_code == 200
    assert second.json()["duplicates"] == 1


def assert_health_ok() -> None:
    response = httpx.get(f"{API_URL}/health", timeout=10.0)
    assert response.status_code == 200
    assert response.json()["status"] in {"OK", "DEGRADED"}


if __name__ == "__main__":
    assert_health_ok()
    assert_metrics_valid()
    assert_funnel_monotonic()
    print("All assertions passed.")
