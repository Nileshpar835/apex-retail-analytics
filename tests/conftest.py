from __future__ import annotations

import os

import pytest
from httpx import ASGITransport, AsyncClient

os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///./test_store_intel.db"
os.environ["DB_AVAILABLE"] = "true"

from app.db_session import init_db
from app.main import app


@pytest.fixture(scope="session")
def anyio_backend():
    return "asyncio"


@pytest.fixture(scope="session", autouse=True)
async def prepare_database():
    if os.path.exists("test_store_intel.db"):
        os.remove("test_store_intel.db")
    await init_db()
    yield
    if os.path.exists("test_store_intel.db"):
        os.remove("test_store_intel.db")


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as async_client:
        yield async_client
