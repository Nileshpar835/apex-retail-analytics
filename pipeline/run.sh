#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VIDEO_ROOT="${VIDEO_ROOT:-$ROOT/data/CCTV}"  # Camera footage directory
STORE_ID="${STORE_ID:-STORE_BLR_002}"
OUTPUT="${OUTPUT:-$ROOT/data/generated_events.jsonl}"
INGEST_URL="${INGEST_URL:-http://localhost:8000}"

python "$ROOT/scripts/prepare_pos.py"
python "$ROOT/pipeline/detect.py" \
  --store-id "$STORE_ID" \
  --video-root "$VIDEO_ROOT" \
  --layout "$ROOT/data/store_layout.json" \
  --output "$OUTPUT" \
  --frame-stride "${FRAME_STRIDE:-5}" \
  ${FAST_MODE:+--fast} \
  --ingest-url "$INGEST_URL"

echo "Pipeline complete. Events written to $OUTPUT"
