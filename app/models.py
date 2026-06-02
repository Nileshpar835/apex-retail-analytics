from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "Store Intelligence API"
    database_url: str = "sqlite+aiosqlite:///./data/store_intel.db"
    store_layout_path: str = "data/store_layout.json"
    pos_transactions_path: str = "data/pos_transactions.csv"
    stale_feed_minutes: int = 10
    conversion_window_minutes: int = 5
    db_available: bool = True
    redis_url: str = "redis://localhost:6379/0"
    vision_events_path: str = "data/store_events.jsonl"
    realtime_publish_interval_seconds: float = 0.2


@lru_cache
def get_settings() -> Settings:
    return Settings()


class EventMetadata(BaseModel):
    queue_depth: int | None = None
    sku_zone: str | None = None
    session_seq: int | None = None


class StoreEvent(BaseModel):
    event_id: str
    store_id: str
    camera_id: str
    visitor_id: str
    event_type: str
    timestamp: str
    zone_id: str | None = None
    dwell_ms: int = 0
    is_staff: bool = False
    confidence: float = Field(ge=0.0, le=1.0)
    metadata: EventMetadata = Field(default_factory=EventMetadata)

    @field_validator("event_type")
    @classmethod
    def validate_event_type(cls, value: str) -> str:
        allowed = {
            "ENTRY",
            "EXIT",
            "ZONE_ENTER",
            "ZONE_EXIT",
            "ZONE_DWELL",
            "BILLING_QUEUE_JOIN",
            "BILLING_QUEUE_ABANDON",
            "REENTRY",
        }
        if value not in allowed:
            raise ValueError(f"Unsupported event_type: {value}")
        return value


class IngestRequest(BaseModel):
    events: list[dict[str, Any]]


class IngestResponse(BaseModel):
    accepted: int
    duplicates: int
    rejected: int
    errors: list[dict[str, Any]]


class ZoneMetric(BaseModel):
    zone_id: str
    avg_dwell_ms: float
    visit_count: int


class StoreMetricsResponse(BaseModel):
    store_id: str
    date: str
    unique_visitors: int
    conversion_rate: float
    avg_dwell_per_zone: list[ZoneMetric]
    queue_depth: int
    abandonment_rate: float
    current_persons: int
    current_staff: int


class FunnelStage(BaseModel):
    stage: str
    count: int
    drop_off_pct: float | None = None


class FunnelResponse(BaseModel):
    store_id: str
    date: str
    stages: list[FunnelStage]


class HeatmapZone(BaseModel):
    zone_id: str
    visit_frequency: float
    avg_dwell_ms: float
    normalized_score: float


class HeatmapResponse(BaseModel):
    store_id: str
    date: str
    zones: list[HeatmapZone]
    data_confidence: str


class Anomaly(BaseModel):
    anomaly_type: str
    severity: str
    message: str
    suggested_action: str
    detected_at: str


class AnomaliesResponse(BaseModel):
    store_id: str
    active_anomalies: list[Anomaly]


class HealthResponse(BaseModel):
    status: str
    stores: list[dict[str, Any]]
    warnings: list[str]


def load_store_layout(path: str | None = None) -> dict[str, Any]:
    settings = get_settings()
    layout_path = Path(path or settings.store_layout_path)
    if not layout_path.is_absolute():
        layout_path = Path(os.getcwd()) / layout_path
    with layout_path.open(encoding="utf-8") as handle:
        return json.load(handle)


def get_store_ids() -> list[str]:
    layout = load_store_layout()
    return [store["store_id"] for store in layout["stores"]]


def resolve_store_aliases(store_id: str) -> set[str]:
    aliases = {store_id}
    layout = load_store_layout()
    for store in layout.get("stores", []):
        primary = str(store.get("store_id", "")).strip()
        legacy = str(store.get("legacy_store_id", "")).strip()
        if store_id in {primary, legacy}:
            if primary:
                aliases.add(primary)
            if legacy:
                aliases.add(legacy)
            break
    return aliases
