from __future__ import annotations

import csv
import json
import logging
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import Base, PosTransactionRecord
from app.models import Settings, get_settings

logger = logging.getLogger(__name__)

_engine = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def get_engine():
    global _engine
    if _engine is None:
        settings = get_settings()
        _engine = create_async_engine(settings.database_url, echo=False)
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(get_engine(), expire_on_commit=False)
    return _session_factory


async def init_db(settings: Settings | None = None) -> None:
    settings = settings or get_settings()
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await seed_pos_transactions(settings)
    from app.seed import seed_sample_events

    session_factory = get_session_factory()
    async with session_factory() as session:
        await seed_sample_events(session)


async def seed_pos_transactions(settings: Settings) -> None:
    pos_path = Path(settings.pos_transactions_path)
    if not pos_path.is_absolute():
        pos_path = Path.cwd() / pos_path
    if not pos_path.exists():
        logger.warning("POS file missing at %s; attempting to prepare from raw CSV", pos_path)
        # Try to prepare from pos_raw.csv
        try:
            from scripts.prepare_pos import main as prepare_main
            prepare_main()
        except Exception as e:
            logger.warning("Failed to prepare POS from raw: %s", e)
            return

    if not pos_path.exists():
        logger.warning("POS file still missing after prep attempt")
        return

    session_factory = get_session_factory()
    async with session_factory() as session:
        existing = await session.scalar(select(PosTransactionRecord.transaction_id).limit(1))
        if existing:
            return

        try:
            with pos_path.open(encoding="utf-8") as handle:
                reader = csv.DictReader(handle)
                if not reader.fieldnames or "transaction_id" not in reader.fieldnames:
                    logger.warning("CSV missing required columns. Expected: transaction_id, store_id, timestamp, basket_value_inr")
                    return
                for row in reader:
                    try:
                        session.add(
                            PosTransactionRecord(
                                transaction_id=row["transaction_id"],
                                store_id=row["store_id"],
                                timestamp=row["timestamp"],
                                basket_value_inr=float(row["basket_value_inr"]),
                            )
                        )
                    except (KeyError, ValueError) as e:
                        logger.warning("Skipping malformed row: %s", e)
                        continue
            await session.commit()
            logger.info("Seeded POS transactions from %s", pos_path)
        except Exception as e:
            logger.warning("Failed to seed POS transactions: %s", e)
            await session.rollback()


async def check_db_health() -> bool:
    settings = get_settings()
    if not settings.db_available:
        return False
    try:
        session_factory = get_session_factory()
        async with session_factory() as session:
            await session.execute(select(PosTransactionRecord.transaction_id).limit(1))
        return True
    except Exception:
        logger.exception("Database health check failed")
        return False
