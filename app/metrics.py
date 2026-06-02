from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import EventRecord, PosTransactionRecord, parse_iso_timestamp
from app.ingestion import fetch_store_events, parse_metadata
from app.models import Settings, StoreMetricsResponse, ZoneMetric, get_settings


def utc_today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def event_date(timestamp: str) -> str:
    return parse_iso_timestamp(timestamp).date().isoformat()


def filter_events_for_date(events: list[EventRecord], date: str | None = None) -> list[EventRecord]:
    if date:
        return [event for event in events if event_date(event.timestamp) == date]
    if not events:
        return []
    latest_date = max(event_date(event.timestamp) for event in events)
    return [event for event in events if event_date(event.timestamp) == latest_date]


def build_sessions(events: list[EventRecord]) -> dict[str, list[EventRecord]]:
    sessions: dict[str, list[EventRecord]] = defaultdict(list)
    for event in events:
        sessions[event.visitor_id].append(event)
    for visitor_events in sessions.values():
        visitor_events.sort(key=lambda item: item.timestamp)
    return sessions


def unique_visitors_from_sessions(sessions: dict[str, list[EventRecord]]) -> set[str]:
    """Extract unique visitor IDs from sessions.
    
    Staff members (is_staff=True) are excluded.
    A visitor is counted once if they have an ENTRY or REENTRY event.
    Same visitor seen on multiple cameras counts as ONE visitor.
    """
    visitors: set[str] = set()
    for visitor_id, visitor_events in sessions.items():
        # Skip staff members entirely
        if any(event.is_staff for event in visitor_events):
            continue
        # Count visitor only if they have an entry event
        if any(event.event_type in {"ENTRY", "REENTRY"} and not event.is_staff for event in visitor_events):
            visitors.add(visitor_id)
    return visitors


async def compute_conversion_rate(
    session: AsyncSession,
    store_id: str,
    events: list[EventRecord],
    settings: Settings | None = None,
) -> tuple[float, set[str]]:
    """Compute conversion rate: transactions / unique customers (staff excluded).
    
    Returns:
        Tuple of (conversion_rate, unique_customers)
    """
    settings = settings or get_settings()
    # Build sessions and get unique customers (excluding staff)
    sessions = build_sessions(events)
    visitors = unique_visitors_from_sessions(sessions)
    
    if not visitors:
        return 0.0, visitors

    pos_result = await session.execute(
        select(PosTransactionRecord).where(PosTransactionRecord.store_id == store_id)
    )
    transactions = list(pos_result.scalars().all())
    converted: set[str] = set()
    window = timedelta(minutes=settings.conversion_window_minutes)

    for visitor_id, visitor_events in sessions.items():
        # Only consider non-staff visitors
        if visitor_id not in visitors or any(e.is_staff for e in visitor_events):
            continue
            
        billing_times = [
            parse_iso_timestamp(event.timestamp)
            for event in visitor_events
            if (event.zone_id == "BILLING"
                or event.event_type in {"BILLING_QUEUE_JOIN", "ZONE_ENTER", "ZONE_DWELL"}
                and event.zone_id == "BILLING")
            and not event.is_staff
        ]
        if not billing_times:
            continue
            
        for txn in transactions:
            txn_time = parse_iso_timestamp(txn.timestamp)
            if any(0 <= (txn_time - billing_time).total_seconds() <= window.total_seconds() for billing_time in billing_times):
                converted.add(visitor_id)
                break

    return round(len(converted) / len(visitors), 4), visitors


def compute_avg_dwell_per_zone(events: list[EventRecord]) -> list[ZoneMetric]:
    """Compute average dwell time per zone (staff excluded).
    
    Only counts events from non-staff visitors.
    """
    dwell_totals: dict[str, int] = defaultdict(int)
    dwell_counts: dict[str, int] = defaultdict(int)
    visit_counts: dict[str, int] = defaultdict(int)

    for event in events:
        # Skip staff events
        if event.is_staff:
            continue
            
        if event.event_type == "ZONE_ENTER" and event.zone_id:
            visit_counts[event.zone_id] += 1
        if event.event_type == "ZONE_DWELL" and event.zone_id:
            dwell_totals[event.zone_id] += event.dwell_ms
            dwell_counts[event.zone_id] += 1

    zone_ids = sorted(set(list(visit_counts.keys()) + list(dwell_totals.keys())))
    metrics: list[ZoneMetric] = []
    for zone_id in zone_ids:
        count = dwell_counts.get(zone_id, 0)
        avg = dwell_totals[zone_id] / count if count else 0.0
        metrics.append(
            ZoneMetric(
                zone_id=zone_id,
                avg_dwell_ms=round(avg, 2),
                visit_count=visit_counts.get(zone_id, 0),
            )
        )
    return metrics


def compute_queue_depth(events: list[EventRecord]) -> int:
    """Compute maximum queue depth at billing (staff excluded).
    
    Tracks ENTRY/EXIT events in billing zone only for non-staff.
    """
    depth = 0
    max_depth = 0
    for event in sorted(events, key=lambda item: item.timestamp):
        # Skip staff in queue tracking
        if event.is_staff:
            continue
            
        if event.zone_id == "BILLING" or event.event_type.startswith("BILLING"):
            if event.event_type in {"ZONE_ENTER", "BILLING_QUEUE_JOIN", "ENTRY", "REENTRY"}:
                depth += 1
            elif event.event_type in {"ZONE_EXIT", "EXIT", "BILLING_QUEUE_ABANDON"}:
                depth = max(depth - 1, 0)
            metadata = parse_metadata(event)
            if metadata.get("queue_depth") is not None:
                max_depth = max(max_depth, int(metadata["queue_depth"]))
    return max(max_depth, depth)


def compute_abandonment_rate(events: list[EventRecord]) -> float:
    """Compute queue abandonment rate (staff excluded).
    
    Rate = abandoned joins / total joins
    """
    # Only count non-staff abandonment events
    joins = sum(1 for event in events if event.event_type == "BILLING_QUEUE_JOIN" and not event.is_staff)
    abandons = sum(1 for event in events if event.event_type == "BILLING_QUEUE_ABANDON" and not event.is_staff)
    if joins == 0:
        return 0.0
    return round(abandons / joins, 4)


def compute_current_occupancy(events: list[EventRecord]) -> tuple[int, int]:
    """Compute current number of persons in shop and current staff count.
    
    Returns:
        Tuple of (current_persons, current_staff)
    
    A person is "currently in shop" if they have an ENTRY/REENTRY event
    but no EXIT event after it (tracked per visitor_id).
    """
    sessions = build_sessions(events)
    current_persons = 0
    current_staff = 0
    
    for visitor_id, visitor_events in sessions.items():
        if not visitor_events:
            continue
        
        # Check if this visitor has an active session (has ENTRY/REENTRY but no EXIT)
        has_entry = False
        is_active = True
        is_staff_visitor = False
        
        for event in visitor_events:
            if event.event_type in {"ENTRY", "REENTRY"}:
                has_entry = True
                is_staff_visitor = event.is_staff
            elif event.event_type == "EXIT":
                is_active = False
        
        # If visitor has entry and no exit, they're currently in shop
        if has_entry and is_active:
            if is_staff_visitor:
                current_staff += 1
            else:
                current_persons += 1
    
    return current_persons, current_staff


async def get_store_metrics(
    session: AsyncSession,
    store_id: str,
    date: str | None = None,
) -> StoreMetricsResponse:
    all_events = await fetch_store_events(session, store_id)
    events = filter_events_for_date(all_events, date)
    sessions = build_sessions(events)
    visitors = unique_visitors_from_sessions(sessions)
    conversion_rate, _ = await compute_conversion_rate(session, store_id, events)
    current_persons, current_staff = compute_current_occupancy(all_events)

    return StoreMetricsResponse(
        store_id=store_id,
        date=date or (event_date(events[0].timestamp) if events else utc_today()),
        unique_visitors=len(visitors),
        conversion_rate=conversion_rate,
        avg_dwell_per_zone=compute_avg_dwell_per_zone(events),
        queue_depth=compute_queue_depth(events),
        abandonment_rate=compute_abandonment_rate(events),
        current_persons=current_persons,
        current_staff=current_staff,
    )
