from __future__ import annotations

import json
import logging
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import EventRecord
from app.ingestion import ingest_events
from app.models import get_settings

logger = logging.getLogger(__name__)


async def seed_sample_events(session: AsyncSession) -> None:
    count = await session.scalar(select(func.count()).select_from(EventRecord))
    if count and count > 0:
        return

    settings = get_settings()
    candidates = [
        Path(settings.store_layout_path).parent / "store_events.jsonl",  # Real POS-based events
        Path(settings.store_layout_path).parent / "sample_events.jsonl",
        Path("data/store_events.jsonl"),
        Path("data/sample_events.jsonl"),
    ]
    sample_path = next((path for path in candidates if path.exists()), None)
    if sample_path is None:
        logger.warning("No events file found for seeding (tried store_events.jsonl and sample_events.jsonl)")
        return

    events: list[dict] = []
    with sample_path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                events.append(json.loads(line))

    result = await ingest_events(session, events)
    logger.info(
        "Seeded events from %s: accepted=%s duplicates=%s rejected=%s",
        sample_path.name,
        result.accepted,
        result.duplicates,
        result.rejected,
    )
