# Store Intelligence Platform

End-to-end retail analytics for **Apex Retail / Purplle Brigade Bangalore** — from CCTV footage to live store intelligence API.

## Quick Start (5 commands)

```bash
git clone <your-repo>
cd store-intelligence
pip install -r requirements.txt
python scripts/prepare_pos.py && python scripts/generate_sample_events.py
docker compose up --build
```

Open:
- API docs: http://localhost:8000/docs
- Live dashboard: http://localhost:8501
- React dashboard: http://localhost:5173
- Metrics: http://localhost:8000/stores/STORE_BLR_002/metrics

`docker compose up --build` starts all three services: API, Python dashboard, and React dashboard.

## Run Detection Pipeline on CCTV Clips

Place the five CCTV files in the `data/CCTV` folder:

- `CAM 1.mp4` — entry/exit
- `CAM 2.mp4` — floor zone A
- `CAM 3.mp4` — floor zone B
- `CAM 4.mp4` — billing
- `CAM 5.mp4` — overlapping floor/entry

### Windows

```powershell
cd store-intelligence
.\pipeline\run.ps1
```

### Linux/macOS

```bash
cd store-intelligence
bash pipeline/run.sh
```

Output events: `data/generated_events.jsonl`

Optional fast mode (motion detection, no YOLO download):

```bash
$env:FAST_MODE="1"; .\pipeline\run.ps1
```

## API Endpoints

| Endpoint | Description |
|---|---|
| `POST /events/ingest` | Batch ingest up to 500 events (idempotent by `event_id`) |
| `GET /stores/{id}/metrics` | Visitors, conversion, dwell, queue, abandonment |
| `GET /stores/{id}/funnel` | Entry → Zone → Billing → Purchase funnel |
| `GET /stores/{id}/heatmap` | Zone intensity normalized 0–100 |
| `GET /stores/{id}/anomalies` | Queue spike, conversion drop, dead zones |
| `GET /health` | Service health + stale feed warnings |
| `GET /ws/dashboard` | WebSocket stream with 1s batches of raw events + Redis analytics |

## Real-Time Redis Stream

The API publishes and consumes realtime events via Redis Pub/Sub channel `store_events`.

- Simulated publisher reads VisionEngine JSON lines from `data/store_events.jsonl`.
- Aggregator maintains `active_footfall`, `queue_length`, and `zone_occupancy` in Redis.
- WebSocket clients connect at `ws://localhost:8000/ws/dashboard`.

Environment variables:

| Variable | Default | Purpose |
|---|---|---|
| `REDIS_URL` | `redis://localhost:6379/0` | Redis connection for Pub/Sub and metrics |
| `VISION_EVENTS_PATH` | `data/store_events.jsonl` | JSONL stream input for simulator |
| `REALTIME_PUBLISH_INTERVAL_SECONDS` | `0.2` | Publish frequency for simulated events |

## React Live Dashboard (Tailwind + Lucide)

Started automatically via Docker Compose at `http://localhost:5173`.

To run it outside Docker:

```bash
cd dashboard/react-dashboard
npm install
npm run dev
```

## Terminal Live Dashboard

```bash
python dashboard/live_dashboard.py --api-url http://localhost:8000
```

## Tests

```bash
pytest --cov=app --cov=pipeline --cov-report=term-missing
python assertions.py
```

## Project Layout

```
store-intelligence/
├── pipeline/          # YOLOv8 detection + tracking + event emission
├── app/               # FastAPI intelligence API
├── dashboard/         # Web + terminal live dashboards
├── tests/             # Pytest suite with AI prompt blocks
├── data/              # store layout, POS, sample events
├── DESIGN.md
└── CHOICES.md
```

## Environment Variables

| Variable | Default | Purpose |
|---|---|---|
| `VIDEO_ROOT` | `./data/CCTV` | Camera footage directory (MP4 files) |
| `DATABASE_URL` | SQLite local path | Event storage |
| `INGEST_URL` | `http://localhost:8000` | Pipeline ingest target |
| `FRAME_STRIDE` | `5` | Process every Nth frame |

## Acceptance Gate Checklist

- [x] `docker compose up` starts API + dashboard
- [x] Detection pipeline documented and runnable
- [x] `POST /events/ingest` accepts batches
- [x] `GET /stores/STORE_BLR_002/metrics` returns JSON
- [x] `DESIGN.md` and `CHOICES.md` included
