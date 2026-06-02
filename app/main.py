from __future__ import annotations

from contextlib import asynccontextmanager
import logging

from fastapi import Depends, FastAPI, HTTPException, Request, WebSocket
from fastapi.responses import JSONResponse, StreamingResponse
from redis.asyncio import Redis
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics import get_store_anomalies, get_store_heatmap
from app.camera import CameraManager
from app.db_session import check_db_health, get_session_factory, init_db
from app.funnel import get_store_funnel
from app.health import get_health_status
from app.ingestion import ingest_events
from app.logging_middleware import StructuredLoggingMiddleware, configure_logging
from app.metrics import get_store_metrics
from app.models import (
    AnomaliesResponse,
    FunnelResponse,
    HealthResponse,
    HeatmapResponse,
    IngestRequest,
    IngestResponse,
    StoreMetricsResponse,
    get_settings,
    resolve_store_aliases,
)
from app.realtime import RealtimeAnalyticsService
from app.tracking import get_tracker
from app.database import PosTransactionRecord
from fastapi.middleware.cors import CORSMiddleware


logger = logging.getLogger(__name__)

camera_manager: CameraManager | None = None
realtime_service: RealtimeAnalyticsService | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global camera_manager, realtime_service
    configure_logging()
    settings = get_settings()
    await init_db(settings)
    
    # Initialize camera manager
    from pathlib import Path
    base_dir = Path(__file__).parent.parent
    cctv_dir = base_dir / "data" / "CCTV"  # Uses footage from data/CCTV
    model_path = base_dir / "yolov8n.pt"
    
    camera_manager = CameraManager(
        data_dir=str(cctv_dir),
        model_path=str(model_path) if model_path.exists() else "yolov8n.pt"
    )

    redis_client: Redis | None = None
    try:
        redis_client = Redis.from_url(
            settings.redis_url,
            encoding="utf-8",
            decode_responses=True,
        )
        await redis_client.ping()
        realtime_service = RealtimeAnalyticsService(
            redis_client,
            settings.vision_events_path,
            publish_interval_seconds=settings.realtime_publish_interval_seconds,
            store_layout_path=settings.store_layout_path,
        )
        await realtime_service.start()
    except Exception:
        logger.exception("Realtime stream disabled because Redis initialization failed")
        realtime_service = None
        if redis_client:
            await redis_client.close()

    yield
    
    # Cleanup
    if realtime_service:
        await realtime_service.stop()
    if camera_manager:
        camera_manager.close_all()


app = FastAPI(title="Store Intelligence API", version="1.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allow all origins for development
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(StructuredLoggingMiddleware)


async def get_db_session() -> AsyncSession:
    session_factory = get_session_factory()
    async with session_factory() as session:
        yield session


@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception):
    if isinstance(exc, HTTPException):
        raise exc
    return JSONResponse(
        status_code=500,
        content={
            "error": "internal_server_error",
            "message": "An unexpected error occurred.",
            "trace_id": getattr(request.state, "trace_id", None),
        },
    )


@app.post("/events/ingest", response_model=IngestResponse)
async def ingest_endpoint(
    payload: IngestRequest,
    request: Request,
    session: AsyncSession = Depends(get_db_session),
) -> IngestResponse:
    if not await check_db_health():
        raise HTTPException(
            status_code=503,
            detail={
                "error": "service_unavailable",
                "message": "Database is unavailable.",
            },
        )
    if len(payload.events) > 500:
        raise HTTPException(status_code=400, detail="Batch size exceeds 500 events.")
    request.state.event_count = len(payload.events)
    return await ingest_events(session, payload.events)


@app.get("/stores/{store_id}/metrics", response_model=StoreMetricsResponse)
async def metrics_endpoint(
    store_id: str,
    session: AsyncSession = Depends(get_db_session),
) -> StoreMetricsResponse:
    _ensure_db()
    return await get_store_metrics(session, store_id)


@app.get("/stores/{store_id}/revenue-summary")
async def revenue_summary_endpoint(
    store_id: str,
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, float | int | str]:
    _ensure_db()
    aliases = resolve_store_aliases(store_id)
    result = await session.execute(
        select(
            func.count(PosTransactionRecord.transaction_id),
            func.coalesce(func.sum(PosTransactionRecord.basket_value_inr), 0.0),
        ).where(PosTransactionRecord.store_id.in_(aliases))
    )
    transaction_count, total_revenue_inr = result.one()
    return {
        "store_id": store_id,
        "transaction_count": int(transaction_count or 0),
        "total_revenue_inr": round(float(total_revenue_inr or 0.0), 2),
    }


@app.get("/stores/{store_id}/funnel", response_model=FunnelResponse)
async def funnel_endpoint(
    store_id: str,
    session: AsyncSession = Depends(get_db_session),
) -> FunnelResponse:
    _ensure_db()
    return await get_store_funnel(session, store_id)


@app.get("/stores/{store_id}/heatmap", response_model=HeatmapResponse)
async def heatmap_endpoint(
    store_id: str,
    session: AsyncSession = Depends(get_db_session),
) -> HeatmapResponse:
    _ensure_db()
    return await get_store_heatmap(session, store_id)


@app.get("/stores/{store_id}/anomalies", response_model=AnomaliesResponse)
async def anomalies_endpoint(
    store_id: str,
    session: AsyncSession = Depends(get_db_session),
) -> AnomaliesResponse:
    _ensure_db()
    return await get_store_anomalies(session, store_id)


@app.get("/health", response_model=HealthResponse)
async def health_endpoint(session: AsyncSession = Depends(get_db_session)) -> HealthResponse:
    return await get_health_status(session)


def _ensure_db() -> None:
    if not get_settings().db_available:
        raise HTTPException(
            status_code=503,
            detail={
                "error": "service_unavailable",
                "message": "Database is unavailable.",
            },
        )


@app.get("/cameras")
async def list_cameras_endpoint() -> dict[str, list[str]]:
    """Get list of available cameras."""
    if not camera_manager:
        return {"cameras": []}
    return {"cameras": camera_manager.get_available_cameras()}


async def _stream_mjpeg(camera_id: str):
    """Stream video as MJPEG format."""
    if not camera_manager:
        yield b""
        return
    
    while True:
        frame_data = camera_manager.get_frame(camera_id)
        if not frame_data:
            yield b""
            continue
        
        frame_bytes, width, height, _ = frame_data
        if not frame_bytes:
            continue
        
        # MJPEG boundary and headers
        yield b"--frame\r\n"
        yield b"Content-Type: image/jpeg\r\n"
        yield f"Content-Length: {len(frame_bytes)}\r\n".encode()
        yield b"Content-Disposition: inline; filename=stream.jpg\r\n\r\n"
        yield frame_bytes
        yield b"\r\n"


@app.get("/cameras/{camera_id}/feed")
async def camera_feed_endpoint(camera_id: str):
    """Stream live camera feed as MJPEG."""
    if not camera_manager or camera_id not in camera_manager.get_available_cameras():
        raise HTTPException(status_code=404, detail="Camera not found")
    
    return StreamingResponse(
        _stream_mjpeg(camera_id),
        media_type="multipart/x-mixed-replace; boundary=frame",
    )


@app.get("/cameras/{camera_id}/detections")
async def camera_detections_endpoint(camera_id: str) -> dict:
    """Get latest detections for a camera."""
    if not camera_manager or camera_id not in camera_manager.get_available_cameras():
        raise HTTPException(status_code=404, detail="Camera not found")
    
    detections = camera_manager.get_detections(camera_id)
    return {
        "camera_id": camera_id,
        "detections": detections,
        "total_detections": len(detections),
    }


@app.get("/tracking/persons")
async def tracking_persons_endpoint() -> dict:
    """Get all currently tracked persons and their details.
    
    Useful for debugging and monitoring person tracking across cameras.
    """
    tracker = get_tracker()
    persons = []
    
    for person_id, signature in tracker.person_signatures.items():
        person_info = tracker.get_person_info(person_id)
        if person_info:
            persons.append(person_info)
    
    return {
        "total_tracked": len(persons),
        "persons": persons,
        "time_threshold_seconds": tracker.time_threshold_seconds,
    }


@app.get("/tracking/staff")
async def tracking_staff_endpoint() -> dict:
    """Get detected staff members (people wearing black uniforms).
    
    Uses automatic black uniform detection to identify staff.
    """
    tracker = get_tracker()
    staff_list = tracker.get_staff_members()
    
    return {
        "total_staff_detected": len(staff_list),
        "staff_detected": staff_list,
        "detection_method": "black_uniform_appearance",
        "description": "Detects staff by analyzing clothing color for black uniforms",
    }


@app.get("/tracking/stats")
async def tracking_stats_endpoint() -> dict:
    """Get person tracking statistics."""
    tracker = get_tracker()
    total_persons = len(tracker.person_signatures)
    total_mappings = len(tracker.person_to_visitor_id)
    staff_count = tracker.get_staff_count()
    
    return {
        "total_unique_persons_tracked": total_persons,
        "staff_count": staff_count,
        "person_visitor_mappings": total_mappings,
        "time_threshold_seconds": tracker.time_threshold_seconds,
        "color_match_threshold": tracker.color_threshold,
        "tracking_method": "appearance_based_visual_similarity",
    }


@app.get("/store-layout")
async def store_layout_endpoint() -> dict:
    """Get store layout with camera zones and polygons."""
    import json
    from pathlib import Path
    
    layout_file = Path(__file__).parent.parent / "data" / "store_layout.json"
    if not layout_file.exists():
        raise HTTPException(status_code=404, detail="Store layout not found")
    
    with open(layout_file, "r") as f:
        layout_data = json.load(f)
    
    return layout_data


@app.websocket("/ws/dashboard")
async def dashboard_websocket(websocket: WebSocket) -> None:
    await websocket.accept()
    if not realtime_service:
        await websocket.send_json(
            {"error": "realtime_unavailable", "message": "Redis realtime stream is unavailable."}
        )
        await websocket.close(code=1013)
        return
    await realtime_service.stream_dashboard(websocket)
