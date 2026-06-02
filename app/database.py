from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, Float, Index, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class EventRecord(Base):
    __tablename__ = "events"

    event_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    store_id: Mapped[str] = mapped_column(String(32), index=True)
    camera_id: Mapped[str] = mapped_column(String(32))
    visitor_id: Mapped[str] = mapped_column(String(64), index=True)
    event_type: Mapped[str] = mapped_column(String(32), index=True)
    timestamp: Mapped[str] = mapped_column(String(32), index=True)
    zone_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    dwell_ms: Mapped[int] = mapped_column(Integer, default=0)
    is_staff: Mapped[bool] = mapped_column(Boolean, default=False)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    metadata_json: Mapped[str] = mapped_column(Text, default="{}")


Index("idx_store_timestamp", EventRecord.store_id, EventRecord.timestamp)


class DailyBaseline(Base):
    __tablename__ = "daily_baselines"

    store_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    date: Mapped[str] = mapped_column(String(16), primary_key=True)
    conversion_rate: Mapped[float] = mapped_column(Float, default=0.0)
    unique_visitors: Mapped[int] = mapped_column(Integer, default=0)


class PosTransactionRecord(Base):
    __tablename__ = "pos_transactions"

    transaction_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    store_id: Mapped[str] = mapped_column(String(32), index=True)
    timestamp: Mapped[str] = mapped_column(String(32), index=True)
    basket_value_inr: Mapped[float] = mapped_column(Float, default=0.0)


def parse_iso_timestamp(value: str) -> datetime:
    normalized = value.replace("Z", "+00:00")
    return datetime.fromisoformat(normalized)
