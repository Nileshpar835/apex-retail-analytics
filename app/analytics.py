from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import DailyBaseline, EventRecord, parse_iso_timestamp
from app.ingestion import fetch_store_events
from app.metrics import (
    build_sessions,
    compute_avg_dwell_per_zone,
    compute_conversion_rate,
    event_date,
    filter_events_for_date,
    utc_today,
    unique_visitors_from_sessions,
)
from app.models import AnomaliesResponse, Anomaly, HeatmapResponse, HeatmapZone


def normalize_scores(values: dict[str, float]) -> dict[str, float]:
    if not values:
        return {}
    max_value = max(values.values()) or 1.0
    return {key: round((value / max_value) * 100, 2) for key, value in values.items()}


async def get_store_heatmap(
    session: AsyncSession,
    store_id: str,
    date: str | None = None,
) -> HeatmapResponse:
    """Generate heatmap showing zone visit frequency and dwell time.
    
    All metrics exclude staff (is_staff=True).
    Each visitor counted once regardless of camera appearance.
    """
    all_events = await fetch_store_events(session, store_id)
    events = filter_events_for_date(all_events, date)
    sessions = build_sessions(events)
    unique_visitors = len(unique_visitors_from_sessions(sessions))

    visit_counts: dict[str, int] = defaultdict(int)
    dwell_totals: dict[str, int] = defaultdict(int)
    dwell_counts: dict[str, int] = defaultdict(int)

    for event in events:
        # Skip staff events
        if event.is_staff:
            continue
        if not event.zone_id:
            continue
        if event.event_type == "ZONE_ENTER":
            visit_counts[event.zone_id] += 1
        if event.event_type == "ZONE_DWELL":
            dwell_totals[event.zone_id] += event.dwell_ms
            dwell_counts[event.zone_id] += 1

    combined_scores = {}
    normalized_visits = normalize_scores({zone: float(count) for zone, count in visit_counts.items()})
    normalized_dwell = normalize_scores(
        {
            zone: (dwell_totals[zone] / dwell_counts[zone] if dwell_counts[zone] else 0.0)
            for zone in set(visit_counts) | set(dwell_totals)
        }
    )

    zones = sorted(set(visit_counts) | set(dwell_totals))
    heatmap_zones: list[HeatmapZone] = []
    for zone_id in zones:
        visit_score = normalized_visits.get(zone_id, 0.0)
        dwell_score = normalized_dwell.get(zone_id, 0.0)
        combined = round((visit_score * 0.6) + (dwell_score * 0.4), 2)
        combined_scores[zone_id] = combined
        heatmap_zones.append(
            HeatmapZone(
                zone_id=zone_id,
                visit_frequency=visit_score,
                avg_dwell_ms=round(
                    dwell_totals[zone_id] / dwell_counts[zone_id] if dwell_counts.get(zone_id) else 0.0,
                    2,
                ),
                normalized_score=combined,
            )
        )

    confidence = "HIGH" if unique_visitors >= 20 else "LOW"
    return HeatmapResponse(
        store_id=store_id,
        date=date or (event_date(events[0].timestamp) if events else utc_today()),
        zones=sorted(heatmap_zones, key=lambda item: item.normalized_score, reverse=True),
        data_confidence=confidence,
    )


async def upsert_baseline(session: AsyncSession, store_id: str, date: str, conversion_rate: float, visitors: int) -> None:
    existing = await session.get(DailyBaseline, {"store_id": store_id, "date": date})
    if existing:
        existing.conversion_rate = conversion_rate
        existing.unique_visitors = visitors
    else:
        session.add(
            DailyBaseline(
                store_id=store_id,
                date=date,
                conversion_rate=conversion_rate,
                unique_visitors=visitors,
            )
        )
    await session.commit()


async def get_store_anomalies(
    session: AsyncSession,
    store_id: str,
    date: str | None = None,
) -> AnomaliesResponse:
    all_events = await fetch_store_events(session, store_id)
    events = filter_events_for_date(all_events, date)
    now = datetime.now(timezone.utc)
    anomalies: list[Anomaly] = []

    queue_joins = [event for event in events if event.event_type == "BILLING_QUEUE_JOIN" and not event.is_staff]
    if queue_joins:
        latest_depths = [
            event
            for event in queue_joins
            if parse_iso_timestamp(event.timestamp) >= now - timedelta(minutes=15)
        ]
        if len(latest_depths) >= 3:
            anomalies.append(
                Anomaly(
                    anomaly_type="BILLING_QUEUE_SPIKE",
                    severity="WARN",
                    message="Billing queue depth has spiked in the last 15 minutes.",
                    suggested_action="Open an additional billing counter or deploy floor staff to billing.",
                    detected_at=now.isoformat().replace("+00:00", "Z"),
                )
            )

    conversion_rate, visitors = await compute_conversion_rate(session, store_id, events)
    await upsert_baseline(session, store_id, date or utc_today(), conversion_rate, len(visitors))

    baseline_result = await session.execute(
        select(DailyBaseline).where(DailyBaseline.store_id == store_id).order_by(DailyBaseline.date.desc()).limit(8)
    )
    baselines = [row for row in baseline_result.scalars().all() if row.date != (date or utc_today())]
    if baselines:
        avg_conversion = sum(row.conversion_rate for row in baselines) / len(baselines)
        if avg_conversion > 0 and conversion_rate < avg_conversion * 0.7:
            anomalies.append(
                Anomaly(
                    anomaly_type="CONVERSION_DROP",
                    severity="CRITICAL",
                    message=(
                        f"Conversion rate {conversion_rate:.2%} is below the recent baseline "
                        f"average of {avg_conversion:.2%}."
                    ),
                    suggested_action="Review staffing, queue flow, and in-store promotions at billing.",
                    detected_at=now.isoformat().replace("+00:00", "Z"),
                )
            )

    zone_last_visit: dict[str, datetime] = {}
    for event in events:
        if event.is_staff:  # Skip staff zone visits
            continue
        if event.zone_id and event.event_type in {'ZONE_ENTER', 'ZONE_DWELL'}:
            zone_last_visit[event.zone_id] = max(
                zone_last_visit.get(event.zone_id, parse_iso_timestamp(event.timestamp)),
                parse_iso_timestamp(event.timestamp),
            )

    for zone_id, last_seen in zone_last_visit.items():
        if now - last_seen >= timedelta(minutes=30):
            anomalies.append(
                Anomaly(
                    anomaly_type="DEAD_ZONE",
                    severity="INFO",
                    message=f"No customer activity detected in zone {zone_id} for over 30 minutes.",
                    suggested_action="Inspect merchandising or redirect floor staff to activate the zone.",
                    detected_at=now.isoformat().replace("+00:00", "Z"),
                )
            )

    if not events:
        anomalies.append(
            Anomaly(
                anomaly_type="DEAD_ZONE",
                severity="INFO",
                message="No customer events recorded today.",
                suggested_action="Verify camera feeds and detection pipeline are running.",
                detected_at=now.isoformat().replace("+00:00", "Z"),
            )
        )

    return AnomaliesResponse(store_id=store_id, active_anomalies=anomalies)
