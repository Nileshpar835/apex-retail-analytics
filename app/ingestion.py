from __future__ import annotations

import json
import logging
from typing import Any

import numpy as np
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import EventRecord
from app.models import IngestResponse, StoreEvent, resolve_store_aliases
from app.tracking import enhance_visitor_id_with_appearance, get_tracker

logger = logging.getLogger(__name__)


async def ingest_events(session: AsyncSession, events: list[dict[str, Any]]) -> IngestResponse:
    accepted = 0
    duplicates = 0
    rejected = 0
    errors: list[dict[str, Any]] = []

    for index, raw_event in enumerate(events):
        try:
            event = StoreEvent.model_validate(raw_event)
        except ValidationError as exc:
            rejected += 1
            errors.append({"index": index, "detail": exc.errors()})
            continue

        existing = await session.get(EventRecord, event.event_id)
        if existing:
            duplicates += 1
            continue

        session.add(
            EventRecord(
                event_id=event.event_id,
                store_id=event.store_id,
                camera_id=event.camera_id,
                visitor_id=event.visitor_id,
                event_type=event.event_type,
                timestamp=event.timestamp,
                zone_id=event.zone_id,
                dwell_ms=event.dwell_ms,
                is_staff=event.is_staff,
                confidence=event.confidence,
                metadata_json=event.metadata.model_dump_json(),
            )
        )
        accepted += 1

    if accepted:
        await session.commit()
    else:
        await session.rollback()

    return IngestResponse(
        accepted=accepted,
        duplicates=duplicates,
        rejected=rejected,
        errors=errors,
    )


async def ingest_events_with_appearance_tracking(
    session: AsyncSession,
    events: list[dict[str, Any]],
    frames: dict[str, np.ndarray] | None = None,
    bboxes: dict[str, list[tuple]] | None = None,
) -> IngestResponse:
    """Ingest events with appearance-based person tracking across cameras.
    
    Enhances visitor_id matching and staff detection using visual appearance.
    
    Args:
        session: Database session
        events: List of event dicts to ingest
        frames: Optional dict mapping event_id -> frame for tracking
        bboxes: Optional dict mapping event_id -> list of bboxes
        
    Returns:
        IngestResponse with ingestion statistics
    """
    accepted = 0
    duplicates = 0
    rejected = 0
    errors: list[dict[str, Any]] = []
    
    frames = frames or {}
    bboxes = bboxes or {}
    
    for index, raw_event in enumerate(events):
        try:
            event = StoreEvent.model_validate(raw_event)
        except ValidationError as exc:
            rejected += 1
            errors.append({"index": index, "detail": exc.errors()})
            continue
        
        existing = await session.get(EventRecord, event.event_id)
        if existing:
            duplicates += 1
            continue
        
        # Apply appearance-based tracking if frame available
        visitor_id = event.visitor_id
        is_staff = event.is_staff
        
        if event.event_id in frames and event.event_id in bboxes:
            frame = frames[event.event_id]
            bbox_list = bboxes[event.event_id]
            
            # Use first bbox if available
            if bbox_list and len(bbox_list) > 0:
                bbox = bbox_list[0]
                try:
                    visitor_id, is_staff = await enhance_visitor_id_with_appearance(
                        session,
                        visitor_id,
                        event.camera_id,
                        frame,
                        bbox,
                    )
                except Exception as e:
                    logger.warning(f"Appearance tracking failed for event {event.event_id}: {e}")
                    # Continue with original IDs if tracking fails
        
        session.add(
            EventRecord(
                event_id=event.event_id,
                store_id=event.store_id,
                camera_id=event.camera_id,
                visitor_id=visitor_id,
                event_type=event.event_type,
                timestamp=event.timestamp,
                zone_id=event.zone_id,
                dwell_ms=event.dwell_ms,
                is_staff=is_staff,
                confidence=event.confidence,
                metadata_json=event.metadata.model_dump_json(),
            )
        )
        accepted += 1
    
    if accepted:
        await session.commit()
    else:
        await session.rollback()
    
    # Cleanup old tracking data
    cleanup_count = get_tracker().cleanup_old_detections()
    if cleanup_count > 0:
        logger.debug(f"Cleaned up {cleanup_count} old person detections from tracker")
    
    return IngestResponse(
        accepted=accepted,
        duplicates=duplicates,
        rejected=rejected,
        errors=errors,
    )


async def fetch_store_events(
    session: AsyncSession,
    store_id: str,
    *,
    customer_only: bool = True,
) -> list[EventRecord]:
    aliases = resolve_store_aliases(store_id)
    query = select(EventRecord).where(EventRecord.store_id.in_(aliases))
    if customer_only:
        query = query.where(EventRecord.is_staff.is_(False))
    query = query.order_by(EventRecord.timestamp.asc())
    result = await session.execute(query)
    return list(result.scalars().all())


def parse_metadata(record: EventRecord) -> dict[str, Any]:
    try:
        return json.loads(record.metadata_json or "{}")
    except json.JSONDecodeError:
        return {}
