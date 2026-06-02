# Engineering Choices — Store Intelligence Platform

This document captures three core engineering decisions, the alternatives considered, what AI tools suggested, and what I ultimately chose for the Brigade Bangalore CCTV dataset.

---

## Decision 1: Detection Model Selection

### Options Considered

| Option | Pros | Cons |
|---|---|---|
| **YOLOv8n + ByteTrack** | Fast, strong person detection, built-in tracking | Needs GPU for fastest throughput |
| RT-DETR | Higher accuracy on crowded scenes | Heavier, slower on CPU |
| MediaPipe Pose | Lightweight | Weaker in crowded retail occlusion |
| Background subtraction only | No model download | Poor group handling, many false positives |

### What AI Suggested

Chat-based comparisons consistently recommended YOLOv8 as the default retail person detector, with ByteTrack for online multi-object tracking. Gemini suggested RT-DETR for billing-queue accuracy; Claude suggested keeping a `--fast` motion fallback for CI/demo machines without GPU.

### What I Chose and Why

**YOLOv8n + ByteTrack** as default, with optional `--fast` motion mode.

Reasoning:
- The footage includes groups, partial occlusion, and re-entry — YOLOv8 handles person class detection better than motion heuristics alone.
- ByteTrack is integrated in Ultralytics, reducing custom tracker code.
- Nano variant keeps CPU processing feasible for ~30-second sample clips while maintaining reasonable recall.
- I documented confidence on every event instead of suppressing uncertain detections, matching the challenge's calibration requirement.

If I had multi-day labelled footage, I would fine-tune YOLO on purple-uniform staff examples. Without labels, heuristic staff tagging is the pragmatic compromise.

---

## Decision 2: Event Schema Design

### Options Considered

| Option | Pros | Cons |
|---|---|---|
| **Normalized stream of atomic events** | Matches challenge schema exactly | Higher volume |
| Session summary records | Smaller payload | Loses dwell granularity and anomaly signals |
| Hybrid (sessions + events) | Easier funnel queries | Two sources of truth |

### What AI Suggested

An LLM proposed adding `bbox`, `track_id`, and `frame_number` top-level fields for debugging. Another suggested merging `ZONE_ENTER` and `ZONE_DWELL` into a single event with optional duration.

### What I Chose and Why

**Strict adherence to the provided event catalogue** with auxiliary details only inside `metadata`.

Reasoning:
- API scoring uses a fixed schema; extra top-level fields risk validation failures.
- Separate instantaneous events (`ENTRY`, `ZONE_ENTER`) from duration events (`ZONE_DWELL`) so metrics can compute average dwell per zone without inferring from enter/exit pairs alone.
- `BILLING_QUEUE_JOIN` carries `metadata.queue_depth` for anomaly detection.
- `REENTRY` is distinct from `ENTRY` to prevent funnel inflation while preserving auditability.

I rejected merging enter/dwell because billing abandonment and dead-zone anomalies depend on explicit zone exit and queue events.

---

## Decision 3: API Architecture — Storage and Real-Time Metrics

### Options Considered

| Option | Pros | Cons |
|---|---|---|
| **SQLite + compute-on-read** | Simple Docker setup, easy tests | Heavy queries at very large scale |
| PostgreSQL + materialized views | Scales to 40 stores | Heavier compose stack |
| Redis stream + worker aggregates | True streaming | More moving parts for take-home window |

### What AI Suggested

AI recommended PostgreSQL with TimescaleDB extensions and Redis pub/sub for dashboard updates. For a hiring challenge, it also noted SQLite is acceptable if documented with scale limits.

### What I Chose and Why

**FastAPI + async SQLAlchemy + SQLite**, computing metrics on read from ingested events, with sample-event seeding for instant demo value.

Reasoning:
- Acceptance gate requires `docker compose up` with no manual steps — SQLite avoids an extra database container while remaining production-aware through structured logging, health checks, and idempotent ingest.
- Session-based funnel logic is implemented in Python for transparency during follow-up interviews.
- POS transactions are seeded at startup from the Brigade CSV so conversion rate is computed, not hard-coded.
- The first scaling bottleneck at 40 live stores would be write throughput and repeated aggregate queries; I'd address that by moving hot metrics to Redis counters and PostgreSQL read replicas — but that complexity isn't justified before proving detection quality.

### Scale Follow-Up (Interview-Ready)

At 40 stores streaming events continuously, **ingest write volume and per-request aggregation** break first. My migration path: partition events by store/day, pre-aggregate funnel stages incrementally on ingest, and expose `/metrics` from rolling windows rather than full-table scans.

---

## Summary

| Decision | Choice | Key Trade-off |
|---|---|---|
| Detection | YOLOv8n + ByteTrack | Accuracy vs CPU cost (mitigated by frame stride) |
| Schema | Atomic canonical events | Volume vs analytics flexibility |
| API | SQLite compute-on-read | Simplicity vs multi-store scale |

These choices prioritise a **working, explainable, demo-ready system** that handles edge cases (staff, re-entry, empty store, queue abandonment) over premature optimisation.
