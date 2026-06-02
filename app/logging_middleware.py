from __future__ import annotations

import logging
import time
import uuid
from typing import Callable

from pythonjsonlogger import jsonlogger
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger("store_intel.access")


def configure_logging() -> None:
    handler = logging.StreamHandler()
    formatter = jsonlogger.JsonFormatter(
        "%(asctime)s %(levelname)s %(name)s %(message)s trace_id=%(trace_id)s "
        "store_id=%(store_id)s endpoint=%(endpoint)s latency_ms=%(latency_ms)s "
        "event_count=%(event_count)s status_code=%(status_code)s"
    )
    handler.setFormatter(formatter)
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(logging.INFO)


class StructuredLoggingMiddleware(BaseHTTPMiddleware):
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        trace_id = request.headers.get("X-Trace-Id", str(uuid.uuid4()))
        request.state.trace_id = trace_id
        start = time.perf_counter()
        store_id = _extract_store_id(request.url.path)
        response = await call_next(request)
        latency_ms = round((time.perf_counter() - start) * 1000, 2)
        event_count = getattr(request.state, "event_count", 0)
        logger.info(
            "request completed",
            extra={
                "trace_id": trace_id,
                "store_id": store_id or "-",
                "endpoint": request.url.path,
                "latency_ms": latency_ms,
                "event_count": event_count,
                "status_code": response.status_code,
            },
        )
        response.headers["X-Trace-Id"] = trace_id
        return response


def _extract_store_id(path: str) -> str | None:
    parts = path.strip("/").split("/")
    if len(parts) >= 2 and parts[0] == "stores":
        return parts[1]
    return None


