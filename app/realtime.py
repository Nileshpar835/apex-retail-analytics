from __future__ import annotations

import asyncio
import json
import logging
import random
import time
from contextlib import suppress
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect
from redis.asyncio import Redis
from redis.exceptions import RedisError

logger = logging.getLogger(__name__)

STORE_EVENTS_CHANNEL = "store_events"


def normalize_camera_id(camera_id: str | None) -> str:
    return (camera_id or "").strip().upper().replace(" ", "_")


def normalize_zone_id(zone_id: str | None) -> str:
    return (zone_id or "").strip().lower().replace(" ", "_")


class RealtimeAnalyticsService:
    def __init__(
        self,
        redis_client: Redis,
        events_file: str,
        *,
        channel: str = STORE_EVENTS_CHANNEL,
        publish_interval_seconds: float = 0.2,
        store_layout_path: str = "data/store_layout.json",
    ) -> None:
        self.redis = redis_client
        self.events_file = Path(events_file)
        self.store_layout_path = Path(store_layout_path)
        self.channel = channel
        self.publish_interval_seconds = publish_interval_seconds
        self._publisher_task: asyncio.Task[None] | None = None
        self._aggregator_task: asyncio.Task[None] | None = None
        self._stop_event = asyncio.Event()
        self._rng = random.Random(42)
        self._events_cache: list[dict[str, Any]] = []
        self._camera_polygons: dict[str, dict[str, list[tuple[float, float]]]] = {}

        self._key_active_footfall = "analytics:active_footfall"
        self._key_queue_members = "analytics:queue_members"
        self._key_cam1_occupancy = "analytics:zone_occupancy:cam_1"
        self._key_cam2_occupancy = "analytics:zone_occupancy:cam_2"
        self._key_active_customers = "analytics:active_customers"
        self._key_active_staff = "analytics:active_staff"

    async def start(self) -> None:
        await self._load_events()
        self._load_camera_polygons()
        self._stop_event.clear()
        self._publisher_task = asyncio.create_task(self._publisher_loop())
        self._aggregator_task = asyncio.create_task(self._aggregator_loop())

    async def stop(self) -> None:
        self._stop_event.set()
        for task in (self._publisher_task, self._aggregator_task):
            if task:
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task

    async def stream_dashboard(self, websocket: WebSocket) -> None:
        pubsub = self.redis.pubsub()
        await pubsub.subscribe(self.channel)
        buffer: list[dict[str, Any]] = []
        last_emit = time.monotonic()

        try:
            while True:
                message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=0.2)
                if message and message.get("data"):
                    data = message["data"]
                    if isinstance(data, bytes):
                        data = data.decode("utf-8")
                    with suppress(json.JSONDecodeError):
                        buffer.append(json.loads(data))

                now = time.monotonic()
                if now - last_emit >= 1.0:
                    payload = {
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "events": buffer,
                        "metrics": await self.get_metrics(),
                    }
                    await websocket.send_json(payload)
                    buffer = []
                    last_emit = now
        except WebSocketDisconnect:
            return
        finally:
            with suppress(Exception):
                await pubsub.unsubscribe(self.channel)
            with suppress(Exception):
                await pubsub.close()

    async def get_metrics(self) -> dict[str, Any]:
        active_footfall = await self.redis.scard(self._key_active_footfall)
        queue_length = await self.redis.scard(self._key_queue_members)
        cam1_count = await self.redis.scard(self._key_cam1_occupancy)
        cam2_count = await self.redis.scard(self._key_cam2_occupancy)
        active_customers = await self.redis.scard(self._key_active_customers)
        staff_on_floor = await self.redis.scard(self._key_active_staff)

        return {
            "active_footfall": int(active_footfall),
            "total_footfall": int(active_footfall),
            "active_customers": int(active_customers),
            "staff_on_floor": int(staff_on_floor),
            "queue_length": int(queue_length),
            "zone_occupancy": {
                "CAM_1": int(cam1_count),
                "CAM_2": int(cam2_count),
            },
        }

    async def _load_events(self) -> None:
        if not self.events_file.exists():
            logger.warning("Vision events file not found: %s", self.events_file)
            self._events_cache = []
            return

        events: list[dict[str, Any]] = []
        with self.events_file.open(encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                with suppress(json.JSONDecodeError):
                    event = json.loads(line)
                    if isinstance(event, dict):
                        events.append(event)
        self._events_cache = events
        logger.info("Loaded %d events for realtime simulation", len(self._events_cache))

    def _enrich_event(self, event: dict[str, Any]) -> dict[str, Any]:
        enriched = dict(event)
        camera_id = normalize_camera_id(str(enriched.get("camera_id", "")))
        zone_id = normalize_zone_id(enriched.get("zone_id"))

        role = "STAFF" if bool(enriched.get("is_staff")) else "CUSTOMER"
        if camera_id == "CAM_4" and zone_id in {"backroom", "cam_4_backroom"}:
            zone_id = "cam_4_backroom"

        enriched["camera_id"] = camera_id
        enriched["zone_id"] = zone_id
        enriched["role"] = role
        x, y = self._pick_visual_coordinates(camera_id, zone_id)
        enriched["x"] = x
        enriched["y"] = y
        return enriched

    def _load_camera_polygons(self) -> None:
        if not self.store_layout_path.exists():
            self._camera_polygons = {}
            return
        try:
            with self.store_layout_path.open(encoding="utf-8") as handle:
                layout = json.load(handle)
        except (OSError, json.JSONDecodeError):
            logger.exception("Failed to load store layout polygons from %s", self.store_layout_path)
            self._camera_polygons = {}
            return

        camera_polygons: dict[str, dict[str, list[tuple[float, float]]]] = {}
        stores = layout.get("stores", []) if isinstance(layout, dict) else []
        for store in stores:
            cameras = store.get("cameras", []) if isinstance(store, dict) else []
            for camera in cameras:
                camera_id = normalize_camera_id(camera.get("camera_id"))
                if not camera_id:
                    continue
                zones = camera.get("zones", []) if isinstance(camera, dict) else []
                for zone in zones:
                    raw_polygon = zone.get("polygon", [])
                    if not isinstance(raw_polygon, list) or len(raw_polygon) < 3:
                        continue
                    polygon: list[tuple[float, float]] = []
                    for point in raw_polygon:
                        if not isinstance(point, list) or len(point) != 2:
                            continue
                        x, y = float(point[0]), float(point[1])
                        polygon.append((x, y))
                    if len(polygon) < 3:
                        continue
                    zone_id = normalize_zone_id(zone.get("zone_id"))
                    if zone_id:
                        camera_polygons.setdefault(camera_id, {})[zone_id] = polygon

        self._camera_polygons = camera_polygons

    def _sample_point_from_polygon(self, polygon: list[tuple[float, float]]) -> tuple[float, float]:
        min_x = min(point[0] for point in polygon)
        max_x = max(point[0] for point in polygon)
        min_y = min(point[1] for point in polygon)
        max_y = max(point[1] for point in polygon)

        for _ in range(25):
            x = self._rng.uniform(min_x, max_x)
            y = self._rng.uniform(min_y, max_y)
            if self._point_in_polygon(x, y, polygon):
                return round(x, 3), round(y, 3)

        centroid_x = sum(point[0] for point in polygon) / len(polygon)
        centroid_y = sum(point[1] for point in polygon) / len(polygon)
        return round(centroid_x, 3), round(centroid_y, 3)

    @staticmethod
    def _point_in_polygon(x: float, y: float, polygon: list[tuple[float, float]]) -> bool:
        inside = False
        j = len(polygon) - 1
        for i in range(len(polygon)):
            xi, yi = polygon[i]
            xj, yj = polygon[j]
            intersects = ((yi > y) != (yj > y)) and (
                x < (xj - xi) * (y - yi) / ((yj - yi) or 1e-9) + xi
            )
            if intersects:
                inside = not inside
            j = i
        return inside

    def _pick_visual_coordinates(self, camera_id: str, zone_id: str) -> tuple[float, float]:
        camera_zones = self._camera_polygons.get(camera_id, {})
        if zone_id in camera_zones:
            return self._sample_point_from_polygon(camera_zones[zone_id])
        if camera_zones:
            fallback_polygon = next(iter(camera_zones.values()))
            return self._sample_point_from_polygon(fallback_polygon)
        return (
            round(self._rng.uniform(0.05, 0.95), 3),
            round(self._rng.uniform(0.05, 0.95), 3),
        )

    async def _publisher_loop(self) -> None:
        if not self._events_cache:
            logger.warning("Realtime publisher has no events to stream")
            return

        index = 0
        total = len(self._events_cache)
        while not self._stop_event.is_set():
            event = self._enrich_event(self._events_cache[index % total])
            try:
                await self.redis.publish(self.channel, json.dumps(event))
            except RedisError:
                logger.exception("Failed to publish to Redis channel %s", self.channel)
                await asyncio.sleep(1.0)
                continue

            index += 1
            await asyncio.sleep(self.publish_interval_seconds)

    async def _aggregator_loop(self) -> None:
        pubsub = self.redis.pubsub()
        await pubsub.subscribe(self.channel)
        try:
            while not self._stop_event.is_set():
                message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
                if not message or not message.get("data"):
                    continue
                data = message["data"]
                if isinstance(data, bytes):
                    data = data.decode("utf-8")
                try:
                    event = json.loads(data)
                except json.JSONDecodeError:
                    continue
                await self._apply_event(event)
        finally:
            with suppress(Exception):
                await pubsub.unsubscribe(self.channel)
            with suppress(Exception):
                await pubsub.close()

    async def _apply_event(self, event: dict[str, Any]) -> None:
        visitor_id = str(event.get("visitor_id", "")).strip()
        if not visitor_id:
            return

        camera_id = normalize_camera_id(event.get("camera_id"))
        zone_id = normalize_zone_id(event.get("zone_id"))
        event_type = str(event.get("event_type", "")).strip().upper()
        role = str(event.get("role", "CUSTOMER")).strip().upper()

        if role == "CUSTOMER":
            if event_type in {"ENTRY", "REENTRY", "ZONE_ENTER", "BILLING_QUEUE_JOIN"}:
                await self.redis.sadd(self._key_active_customers, visitor_id)
            elif event_type in {"EXIT", "ZONE_EXIT", "BILLING_COMPLETED", "BILLING_QUEUE_ABANDON"}:
                await self.redis.srem(self._key_active_customers, visitor_id)
        else:
            if event_type in {"ENTRY", "REENTRY", "ZONE_ENTER"}:
                await self.redis.sadd(self._key_active_staff, visitor_id)
            elif event_type in {"EXIT", "ZONE_EXIT"}:
                await self.redis.srem(self._key_active_staff, visitor_id)

        if role == "CUSTOMER" and camera_id == "CAM_3" and event_type in {"ENTRY", "REENTRY", "ZONE_ENTER"}:
            await self.redis.sadd(self._key_active_footfall, visitor_id)

        if role == "CUSTOMER" and camera_id == "CAM_5":
            joined_queue = event_type == "BILLING_QUEUE_JOIN" or zone_id in {"checkout_queue", "checkout"}
            left_queue = event_type in {"BILLING_COMPLETED", "BILLING_QUEUE_ABANDON", "EXIT", "ZONE_EXIT"}
            if joined_queue:
                await self.redis.sadd(self._key_queue_members, visitor_id)
            elif left_queue:
                await self.redis.srem(self._key_queue_members, visitor_id)

        if role == "CUSTOMER" and camera_id in {"CAM_1", "CAM_2"}:
            occupancy_key = self._key_cam1_occupancy if camera_id == "CAM_1" else self._key_cam2_occupancy
            if event_type in {"ENTRY", "REENTRY", "ZONE_ENTER", "ZONE_DWELL"}:
                await self.redis.sadd(occupancy_key, visitor_id)
            elif event_type in {"EXIT", "ZONE_EXIT", "BILLING_QUEUE_JOIN", "BILLING_COMPLETED", "BILLING_QUEUE_ABANDON"}:
                await self.redis.srem(occupancy_key, visitor_id)
