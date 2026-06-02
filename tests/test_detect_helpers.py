# PROMPT: Test detect.py helper functions without running full YOLO inference.
# CHANGES MADE: Covered layout loading, store lookup, and overlap dedupe logic only.

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pipeline.detect import dedupe_overlap_events, get_store_config, load_layout


def test_load_layout_and_store_config():
    layout_path = Path(__file__).resolve().parents[1] / "data" / "store_layout.json"
    layout = load_layout(layout_path)
    store = get_store_config(layout, "STORE_BLR_002")
    assert store["legacy_store_id"] == "ST1008"
    assert len(store["cameras"]) == 5


def test_dedupe_overlap_events():
    events = [
        {"camera_id": "CAM_FLOOR_03", "event_type": "ENTRY", "visitor_id": "VIS_1"},
        {"camera_id": "CAM_FLOOR_03", "event_type": "ENTRY", "visitor_id": "VIS_1"},
        {"camera_id": "CAM_ENTRY_01", "event_type": "ENTRY", "visitor_id": "VIS_2"},
    ]
    deduped = dedupe_overlap_events(events, "CAM_FLOOR_03")
    assert len(deduped) == 2


def test_get_store_config_invalid():
    layout = load_layout(Path(__file__).resolve().parents[1] / "data" / "store_layout.json")
    with pytest.raises(ValueError):
        get_store_config(layout, "UNKNOWN")
