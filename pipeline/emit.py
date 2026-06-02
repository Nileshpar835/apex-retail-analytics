from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any


EVENT_TYPES = {
    "ENTRY",
    "EXIT",
    "ZONE_ENTER",
    "ZONE_EXIT",
    "ZONE_DWELL",
    "BILLING_QUEUE_JOIN",
    "BILLING_QUEUE_ABANDON",
    "REENTRY",
}


@dataclass
class EventEmitter:
    store_id: str
    camera_id: str
    clip_start_utc: str
    session_seq: dict[str, int] = field(default_factory=dict)

    def _next_seq(self, visitor_id: str) -> int:
        self.session_seq[visitor_id] = self.session_seq.get(visitor_id, 0) + 1
        return self.session_seq[visitor_id]

    def frame_timestamp(self, frame_index: int, fps: float) -> str:
        start = datetime.fromisoformat(self.clip_start_utc.replace("Z", "+00:00"))
        offset = timedelta(seconds=frame_index / max(fps, 1.0))
        return (start + offset).isoformat().replace("+00:00", "Z")

    def emit(
        self,
        *,
        visitor_id: str,
        event_type: str,
        frame_index: int,
        fps: float,
        zone_id: str | None = None,
        dwell_ms: int = 0,
        is_staff: bool = False,
        confidence: float = 0.8,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if event_type not in EVENT_TYPES:
            raise ValueError(f"Invalid event type: {event_type}")

        payload = {
            "event_id": str(uuid.uuid4()),
            "store_id": self.store_id,
            "camera_id": self.camera_id,
            "visitor_id": visitor_id,
            "event_type": event_type,
            "timestamp": self.frame_timestamp(frame_index, fps),
            "zone_id": zone_id,
            "dwell_ms": dwell_ms,
            "is_staff": is_staff,
            "confidence": round(confidence, 2),
            "metadata": {
                "queue_depth": None,
                "sku_zone": None,
                "session_seq": self._next_seq(visitor_id),
            },
        }
        if metadata:
            payload["metadata"].update(metadata)
        return payload

    @staticmethod
    def write_jsonl(events: list[dict[str, Any]], output_path: str) -> None:
        with open(output_path, "w", encoding="utf-8") as handle:
            for event in events:
                handle.write(json.dumps(event) + "\n")
