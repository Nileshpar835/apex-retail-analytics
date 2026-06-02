from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import PosTransactionRecord, parse_iso_timestamp
from app.ingestion import fetch_store_events
from app.metrics import build_sessions, event_date, filter_events_for_date, utc_today
from app.models import FunnelResponse, FunnelStage, resolve_store_aliases


def session_reached_zone(events: list, zone_id: str) -> bool:
    """Check if a visitor session reached a specific zone (staff excluded)."""
    return any(
        event.zone_id == zone_id
        and event.event_type in {"ZONE_ENTER", "ZONE_DWELL", "BILLING_QUEUE_JOIN"}
        and not event.is_staff
        for event in events
    )


def session_reached_any_zone(events: list) -> bool:
    """Check if a visitor session reached any product zone (staff excluded)."""
    product_zones = {"SKINCARE", "MAKEUP", "HAIR", "FRAGRANCE", "ACCESSORIES"}
    return any(session_reached_zone(events, zone) for zone in product_zones)


def session_reached_billing(events: list) -> bool:
    """Check if a visitor session reached billing zone (staff excluded)."""
    return any(
        (event.zone_id == "BILLING"
         or event.event_type in {"BILLING_QUEUE_JOIN", "BILLING_QUEUE_ABANDON", "ZONE_ENTER", "ZONE_DWELL"}
         and event.zone_id == "BILLING")
        and not event.is_staff
        for event in events
    )


async def session_converted(
    session: AsyncSession,
    store_id: str,
    events: list,
    conversion_window_minutes: int = 5,
) -> bool:
    """Check if a visitor session resulted in a purchase (staff excluded)."""
    billing_times = [
        parse_iso_timestamp(event.timestamp)
        for event in events
        if (event.zone_id == "BILLING"
            or (event.event_type in {"BILLING_QUEUE_JOIN", "ZONE_ENTER", "ZONE_DWELL"}
                and event.zone_id == "BILLING"))
        and not event.is_staff
    ]
    if not billing_times:
        return False

    pos_result = await session.execute(
        select(PosTransactionRecord).where(PosTransactionRecord.store_id.in_(resolve_store_aliases(store_id)))
    )
    transactions = list(pos_result.scalars().all())
    window = timedelta(minutes=conversion_window_minutes)
    for txn in transactions:
        txn_time = parse_iso_timestamp(txn.timestamp)
        if any(0 <= (txn_time - billing_time).total_seconds() <= window.total_seconds() for billing_time in billing_times):
            return True
    return False


def primary_session_events(visitor_events: list) -> list:
    """Use the first visit session for funnel attribution; ignore re-entry inflation."""
    exit_indices = [index for index, event in enumerate(visitor_events) if event.event_type == "EXIT"]
    if exit_indices:
        return visitor_events[: exit_indices[0] + 1]
    return visitor_events


async def get_store_funnel(
    session: AsyncSession,
    store_id: str,
    date: str | None = None,
) -> FunnelResponse:
    """Generate funnel stages: Entry → Zone Visit → Billing Queue → Purchase.
    
    All counts exclude staff (is_staff=True).
    Each visitor counted once per entry (deduplication across cameras).
    """
    all_events = await fetch_store_events(session, store_id)
    events = filter_events_for_date(all_events, date)
    sessions = build_sessions(events)

    # Only count non-staff entry sessions
    entry_sessions = {
        visitor_id: primary_session_events(visitor_events)
        for visitor_id, visitor_events in sessions.items()
        if any(event.event_type == "ENTRY" and not event.is_staff for event in visitor_events)
        and not any(e.is_staff for e in visitor_events)  # Entire session must be non-staff
    }

    entry_count = len(entry_sessions)
    zone_visitor_ids: set[str] = set()
    billing_visitor_ids: set[str] = set()
    for visitor_id, visitor_events in entry_sessions.items():
        if session_reached_any_zone(visitor_events):
            zone_visitor_ids.add(visitor_id)
        if session_reached_billing(visitor_events):
            billing_visitor_ids.add(visitor_id)
    bill_after_zone_ids = zone_visitor_ids & billing_visitor_ids

    zone_count = len(zone_visitor_ids)
    billing_count = len(bill_after_zone_ids)
    purchase_count = 0
    for visitor_id in bill_after_zone_ids:
        visitor_events = entry_sessions[visitor_id]
        if await session_converted(session, store_id, visitor_events):
            purchase_count += 1

    def drop_off(current: int, previous: int) -> float | None:
        if previous == 0:
            return None
        return round(((previous - current) / previous) * 100, 2)

    stages = [
        FunnelStage(stage="Entry", count=entry_count, drop_off_pct=None),
        FunnelStage(stage="Zone Visit", count=zone_count, drop_off_pct=drop_off(zone_count, entry_count)),
        FunnelStage(
            stage="Billing Queue",
            count=billing_count,
            drop_off_pct=drop_off(billing_count, zone_count if zone_count else entry_count),
        ),
        FunnelStage(
            stage="Purchase",
            count=purchase_count,
            drop_off_pct=drop_off(purchase_count, billing_count if billing_count else entry_count),
        ),
    ]

    return FunnelResponse(
        store_id=store_id,
        date=date or (event_date(events[0].timestamp) if events else utc_today()),
        stages=stages,
    )
