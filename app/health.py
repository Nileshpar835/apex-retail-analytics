from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import EventRecord, parse_iso_timestamp
from app.db_session import check_db_health
from app.models import HealthResponse, get_store_ids


async def get_health_status(session: AsyncSession) -> HealthResponse:
    db_ok = await check_db_health()
    if not db_ok:
        return HealthResponse(status="DEGRADED", stores=[], warnings=["DATABASE_UNAVAILABLE"])

    warnings: list[str] = []
    stores: list[dict] = []
    now = datetime.now(timezone.utc)

    for store_id in get_store_ids():
        result = await session.execute(
            select(func.max(EventRecord.timestamp)).where(EventRecord.store_id == store_id)
        )
        last_timestamp = result.scalar_one_or_none()
        lag_minutes = None
        if last_timestamp:
            delta = now - parse_iso_timestamp(last_timestamp)
            lag_minutes = round(max(delta.total_seconds(), 0) / 60, 2)
            if delta > timedelta(minutes=10):
                warnings.append(f"STALE_FEED:{store_id}")
        else:
            warnings.append(f"STALE_FEED:{store_id}")

        stores.append(
            {
                "store_id": store_id,
                "last_event_timestamp": last_timestamp,
                "lag_minutes": lag_minutes,
            }
        )

    status = "OK" if not warnings else "DEGRADED"
    return HealthResponse(status=status, stores=stores, warnings=warnings)
