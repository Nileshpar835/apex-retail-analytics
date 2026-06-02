from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import cv2
import httpx

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pipeline.emit import EventEmitter
from pipeline.tracker import (
    VisitorRegistry,
    TrackState,
    crossed_line,
    detect_staff,
    normalized_center,
    point_in_polygon,
)


def load_layout(layout_path: Path) -> dict:
    with layout_path.open(encoding="utf-8") as handle:
        return json.load(handle)


def get_store_config(layout: dict, store_id: str) -> dict:
    for store in layout["stores"]:
        if store["store_id"] == store_id:
            return store
    raise ValueError(f"Unknown store_id: {store_id}")


def process_camera(
    store: dict,
    camera: dict,
    video_root: Path,
    *,
    frame_stride: int = 3,
    max_frames: int | None = None,
    use_yolo: bool = True,
) -> list[dict]:
    video_path = video_root / camera["video_file"]
    if not video_path.exists():
        raise FileNotFoundError(f"Missing video: {video_path}")

    cap = cv2.VideoCapture(str(video_path))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    emitter = EventEmitter(
        store_id=store["store_id"],
        camera_id=camera["camera_id"],
        clip_start_utc=camera["clip_start_utc"],
    )
    registry = VisitorRegistry()
    tracks: dict[int, TrackState] = {}
    events: list[dict] = []
    billing_queue = 0
    frame_index = 0
    processed = 0

    model = None
    if use_yolo:
        from ultralytics import YOLO

        model = YOLO("yolov8n.pt")

    zones = camera.get("zones", [])
    entry_line = camera.get("entry_line")
    role = camera.get("role", "floor")

    while cap.isOpened():
        ok, frame = cap.read()
        if not ok:
            break
        if frame_index % frame_stride != 0:
            frame_index += 1
            continue
        if max_frames is not None and processed >= max_frames:
            break
        processed += 1

        detections: list[tuple[tuple[float, float, float, float], float, int | None]] = []
        if model is not None:
            results = model.track(
                frame,
                persist=True,
                classes=[0],
                conf=0.25,
                iou=0.5,
                verbose=False,
            )
            if results and results[0].boxes is not None:
                boxes = results[0].boxes
                for box in boxes:
                    xyxy = box.xyxy[0].tolist()
                    conf = float(box.conf[0]) if box.conf is not None else 0.5
                    track_id = int(box.id[0]) if box.id is not None else None
                    detections.append((tuple(xyxy), conf, track_id))
        else:
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            blur = cv2.GaussianBlur(gray, (5, 5), 0)
            _, thresh = cv2.threshold(blur, 0, 255, cv2.THRESH_OTSU)
            contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            for idx, contour in enumerate(contours):
                x, y, w, h = cv2.boundingRect(contour)
                if h < height * 0.08 or w < width * 0.03:
                    continue
                detections.append(((x, y, x + w, y + h), 0.4, idx + 1))

        active_track_ids = set()
        timestamp = datetime.fromisoformat(emitter.frame_timestamp(frame_index, fps).replace("Z", "+00:00"))

        for bbox, confidence, track_id in detections:
            if track_id is None:
                continue
            active_track_ids.add(track_id)
            center = normalized_center(bbox, width, height)
            signature = registry.signature(bbox, frame)

            in_billing = any(
                zone["zone_id"] == "BILLING"
                and point_in_polygon(center[0], center[1], zone["polygon"])
                for zone in zones
            )
            is_staff, staff_conf = detect_staff(frame, bbox, 1.0 if in_billing and role == "billing" else 0.0)

            if track_id not in tracks:
                visitor_id, reentry = registry.resolve_visitor(track_id, signature, timestamp, is_staff=is_staff)
                tracks[track_id] = TrackState(
                    track_id=track_id,
                    visitor_id=visitor_id,
                    is_staff=is_staff,
                    appearance_hash=signature,
                )
                if role == "entry_exit" and not is_staff:
                    if reentry == "REENTRY":
                        events.append(
                            emitter.emit(
                                visitor_id=visitor_id,
                                event_type="REENTRY",
                                frame_index=frame_index,
                                fps=fps,
                                zone_id="ENTRY",
                                confidence=confidence,
                                is_staff=False,
                                metadata={"sku_zone": "FOYER"},
                            )
                        )
                    else:
                        events.append(
                            emitter.emit(
                                visitor_id=visitor_id,
                                event_type="ENTRY",
                                frame_index=frame_index,
                                fps=fps,
                                zone_id="ENTRY",
                                confidence=confidence,
                                is_staff=False,
                                metadata={"sku_zone": "FOYER"},
                            )
                        )
                tracks[track_id].session_started = True

            track = tracks[track_id]
            track.is_staff = track.is_staff or is_staff

            if entry_line and role == "entry_exit" and not track.is_staff:
                crossing = crossed_line(track.last_center, center, entry_line)
                if crossing == "ENTRY" and not track.session_started:
                    events.append(
                        emitter.emit(
                            visitor_id=track.visitor_id,
                            event_type="ENTRY",
                            frame_index=frame_index,
                            fps=fps,
                            zone_id="ENTRY",
                            confidence=confidence,
                            metadata={"sku_zone": "FOYER"},
                        )
                    )
                    track.session_started = True
                elif crossing == "EXIT" and track.session_started:
                    events.append(
                        emitter.emit(
                            visitor_id=track.visitor_id,
                            event_type="EXIT",
                            frame_index=frame_index,
                            fps=fps,
                            zone_id="ENTRY",
                            confidence=confidence,
                            metadata={"sku_zone": "FOYER"},
                        )
                    )
                    registry.mark_exit(track.appearance_hash, track.visitor_id, timestamp)
                    track.exited = True

            current_zones = set()
            for zone in zones:
                if point_in_polygon(center[0], center[1], zone["polygon"]):
                    current_zones.add(zone["zone_id"])

            for zone_id in current_zones - track.current_zones:
                metadata = {"sku_zone": next((z["sku_zone"] for z in zones if z["zone_id"] == zone_id), zone_id)}
                events.append(
                    emitter.emit(
                        visitor_id=track.visitor_id,
                        event_type="ZONE_ENTER",
                        frame_index=frame_index,
                        fps=fps,
                        zone_id=zone_id,
                        confidence=max(confidence, staff_conf if track.is_staff else confidence),
                        is_staff=track.is_staff,
                        metadata=metadata,
                    )
                )
                track.zone_enter_frame[zone_id] = frame_index
                track.last_dwell_emit[zone_id] = frame_index
                if zone_id == "BILLING" and billing_queue > 0 and not track.is_staff:
                    events.append(
                        emitter.emit(
                            visitor_id=track.visitor_id,
                            event_type="BILLING_QUEUE_JOIN",
                            frame_index=frame_index,
                            fps=fps,
                            zone_id="BILLING",
                            confidence=confidence,
                            metadata={"queue_depth": billing_queue, "sku_zone": "CHECKOUT"},
                        )
                    )
                    track.billing_joined = True

            for zone_id in track.current_zones - current_zones:
                events.append(
                    emitter.emit(
                        visitor_id=track.visitor_id,
                        event_type="ZONE_EXIT",
                        frame_index=frame_index,
                        fps=fps,
                        zone_id=zone_id,
                        confidence=confidence,
                        is_staff=track.is_staff,
                        metadata={"sku_zone": zone_id},
                    )
                )
                if zone_id == "BILLING" and track.billing_joined and not track.is_staff:
                    events.append(
                        emitter.emit(
                            visitor_id=track.visitor_id,
                            event_type="BILLING_QUEUE_ABANDON",
                            frame_index=frame_index,
                            fps=fps,
                            zone_id="BILLING",
                            confidence=confidence,
                            metadata={"sku_zone": "CHECKOUT"},
                        )
                    )
                    track.billing_joined = False

            for zone_id in current_zones:
                entered_frame = track.zone_enter_frame.get(zone_id, frame_index)
                dwell_frames = frame_index - track.last_dwell_emit.get(zone_id, entered_frame)
                dwell_seconds = (dwell_frames * frame_stride) / fps
                if dwell_seconds >= 30:
                    dwell_ms = int(dwell_seconds * 1000)
                    events.append(
                        emitter.emit(
                            visitor_id=track.visitor_id,
                            event_type="ZONE_DWELL",
                            frame_index=frame_index,
                            fps=fps,
                            zone_id=zone_id,
                            dwell_ms=dwell_ms,
                            confidence=confidence,
                            is_staff=track.is_staff,
                            metadata={"sku_zone": zone_id},
                        )
                    )
                    track.last_dwell_emit[zone_id] = frame_index

            track.current_zones = current_zones
            track.last_center = center
            if "BILLING" in current_zones and not track.is_staff:
                billing_queue = max(billing_queue, len([tid for tid in active_track_ids if tid in tracks and "BILLING" in tracks[tid].current_zones]))

        frame_index += 1

    cap.release()
    return events


def dedupe_overlap_events(events: list[dict], overlap_camera: str) -> list[dict]:
    seen_entries: set[str] = set()
    filtered: list[dict] = []
    for event in events:
        if event["camera_id"] == overlap_camera and event["event_type"] in {"ENTRY", "REENTRY"}:
            key = f"{event['visitor_id']}:{event['event_type']}"
            if key in seen_entries:
                continue
            seen_entries.add(key)
        filtered.append(event)
    return filtered


def run_pipeline(
    *,
    store_id: str,
    video_root: Path,
    layout_path: Path,
    output_path: Path,
    frame_stride: int = 3,
    max_frames: int | None = None,
    fast: bool = False,
) -> list[dict]:
    layout = load_layout(layout_path)
    store = get_store_config(layout, store_id)
    all_events: list[dict] = []
    overlap_camera = None

    for camera in store["cameras"]:
        if camera.get("overlap_with"):
            overlap_camera = camera["camera_id"]
        camera_events = process_camera(
            store,
            camera,
            video_root,
            frame_stride=frame_stride,
            max_frames=max_frames,
            use_yolo=not fast,
        )
        all_events.extend(camera_events)

    if overlap_camera:
        all_events = dedupe_overlap_events(all_events, overlap_camera)

    all_events.sort(key=lambda item: item["timestamp"])
    EventEmitter.write_jsonl(all_events, str(output_path))
    return all_events


def ingest_events(api_url: str, events: list[dict], batch_size: int = 100) -> None:
    with httpx.Client(timeout=60.0) as client:
        for start in range(0, len(events), batch_size):
            batch = events[start : start + batch_size]
            response = client.post(f"{api_url.rstrip('/')}/events/ingest", json={"events": batch})
            response.raise_for_status()


def main() -> None:
    parser = argparse.ArgumentParser(description="Store Intelligence detection pipeline")
    parser.add_argument("--store-id", default="STORE_BLR_002")
    parser.add_argument("--video-root", default=os.environ.get("VIDEO_ROOT", str(ROOT / "data" / "CCTV")))
    parser.add_argument("--layout", default=str(ROOT / "data" / "store_layout.json"))
    parser.add_argument("--output", default=str(ROOT / "data" / "generated_events.jsonl"))
    parser.add_argument("--frame-stride", type=int, default=5)
    parser.add_argument("--max-frames", type=int, default=None)
    parser.add_argument("--fast", action="store_true", help="Use motion detection instead of YOLO")
    parser.add_argument("--ingest-url", default=None, help="POST generated events to API")
    args = parser.parse_args()

    events = run_pipeline(
        store_id=args.store_id,
        video_root=Path(args.video_root),
        layout_path=Path(args.layout),
        output_path=Path(args.output),
        frame_stride=args.frame_stride,
        max_frames=args.max_frames,
        fast=args.fast,
    )
    print(f"Generated {len(events)} events -> {args.output}")

    if args.ingest_url:
        ingest_events(args.ingest_url, events)
        print(f"Ingested events into {args.ingest_url}")


if __name__ == "__main__":
    main()
