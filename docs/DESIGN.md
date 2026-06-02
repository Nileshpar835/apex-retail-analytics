# Design Document — Store Intelligence Platform

## Overview

This system converts anonymised retail CCTV footage into actionable store intelligence for Apex Retail's offline channel. The architecture follows a four-stage pipeline aligned with the challenge specification: **Detection → Event Stream → Intelligence API → Live Dashboard**.

The Brigade Bangalore store (`STORE_BLR_002`, legacy POS id `ST1008`) is modelled using five camera angles mapped to entry, floor, billing, and overlap coverage defined in `data/store_layout.json`. POS transactions from the provided Brigade CSV are normalised into `data/pos_transactions.csv` for conversion-rate correlation.

## Architecture

```
CCTV Clips (camera1-5.mp4)
        │
        ▼
┌───────────────────────┐
│  pipeline/detect.py   │  YOLOv8n person detection + ByteTrack
│  pipeline/tracker.py  │  Zone polygons, entry line, re-entry registry
│  pipeline/emit.py     │  Canonical event schema emission
└───────────┬───────────┘
            │ JSONL / HTTP batches
            ▼
┌───────────────────────┐
│  POST /events/ingest  │  Validation, dedup by event_id, SQLite storage
└───────────┬───────────┘
            │
            ▼
┌───────────────────────────────────────────────┐
│  Analytics Layer                               │
│  metrics.py   → visitors, conversion, dwell    │
│  funnel.py    → session-based funnel           │
│  analytics.py → heatmap + anomalies            │
│  health.py    → stale feed detection           │
└───────────┬───────────────────────────────────┘
            │
            ▼
┌───────────────────────┐
│  dashboard/           │  Web UI (8501) + Rich terminal dashboard
└───────────────────────┘
```

## Detection Layer

The detection pipeline uses **YOLOv8n** for person detection with built-in **ByteTrack** tracking. Each track receives a visitor token from a lightweight re-identification registry that hashes bounding-box size and torso colour. When a person exits and returns within 45 minutes, a `REENTRY` event is emitted instead of a duplicate `ENTRY`.

Zone classification is rule-based: camera-specific polygons (normalised coordinates) determine whether a visitor enters SKINCARE, MAKEUP, HAIR, FRAGRANCE, ACCESSORIES, BILLING, or ENTRY zones. Dwell events fire every 30 seconds of continuous presence. Staff are detected via purple uniform hue in HSV space and extended billing-zone presence; staff events are flagged `is_staff=true`.

Entry and exit are detected on `CAM_ENTRY_01` using a configurable threshold line. Overlap camera `CAM_FLOOR_03` deduplicates redundant entry events.

## Event Stream

Events conform to the required schema with UUID `event_id`, ISO-8601 UTC timestamps derived from clip start + frame offset, and metadata for queue depth, SKU zone labels, and session sequence numbers. Low-confidence detections are retained rather than silently dropped.

## Intelligence API

FastAPI serves REST endpoints backed by **SQLite** via SQLAlchemy async. Ingestion is idempotent on `event_id` and supports partial success for malformed events. Metrics exclude staff sessions. Conversion rate correlates billing-zone presence within a five-minute window before POS transaction timestamps.

Anomaly detection covers billing queue spikes, conversion drops versus rolling baseline, and dead zones with no activity for 30 minutes. The health endpoint reports per-store last-event timestamps and raises `STALE_FEED` warnings after ten minutes of lag.

## Production Concerns

- Structured JSON logging with `trace_id`, `store_id`, endpoint, latency, and ingest batch size
- Docker Compose for one-command deployment
- Graceful 503 responses when database availability flag is disabled
- Pytest coverage across ingest, metrics, funnel, anomalies, and pipeline helpers

## AI-Assisted Decisions

1. **Zone mapping strategy** — I asked an LLM to propose zone polygons from the Brigade layout diagram. The model suggested fine-grained brand-level zones (Maybelline, Faces Canada, etc.). I **overrode** this to coarser merchandising categories (SKINCARE, MAKEUP, HAIR) because the CCTV angles cannot reliably resolve individual brand bays; coarser zones improve robustness and still support heatmap and funnel analytics.

2. **Staff detection approach** — AI recommended a dedicated uniform classifier trained on labelled staff clips. Without labelled staff data, I **rejected** full classifier training and implemented a pragmatic HSV purple-ratio heuristic plus billing-station persistence. This trades precision for zero-shot deployability and explicit `is_staff` flags.

3. **Test generation** — Copilot-style prompts generated the initial pytest skeleton. I **edited** tests to include prompt/change headers required by the challenge, added idempotency and partial-success cases, and removed brittle hard-coded anomaly counts that would fail across dates.

## Data Assets

| File | Purpose |
|---|---|
| `data/store_layout.json` | Cameras, zones, entry line, clip timestamps |
| `data/pos_transactions.csv` | Normalised POS for conversion correlation |
| `data/sample_events.jsonl` | Seed events for API bootstrapping and tests |
| `data/pos_raw.csv` | Original Brigade POS export |

## North Star Alignment

Every design choice supports **offline conversion rate** accuracy and actionability: detection quality affects visitor counts, POS correlation affects conversion, funnel/heatmap expose drop-offs, and anomalies trigger operational responses (queue staffing, merchandising checks, feed monitoring).
