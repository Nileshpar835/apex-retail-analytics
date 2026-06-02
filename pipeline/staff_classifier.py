from __future__ import annotations

import cv2
import numpy as np

# HSV thresholds used to define "black/dark" clothing pixels.
DARK_VALUE_MAX = 75
DARK_SATURATION_MAX = 70

# Full-black uniform thresholds: both upper and lower body should be dark.
DARK_UPPER_THRESHOLD = 0.45
DARK_LOWER_THRESHOLD = 0.45
DARK_OVERALL_THRESHOLD = 0.42

# Slightly relaxed thresholds for billing-camera perspectives.
RELAXED_DARK_UPPER_THRESHOLD = 0.42
RELAXED_DARK_LOWER_THRESHOLD = 0.42
RELAXED_DARK_OVERALL_THRESHOLD = 0.38


def dark_outfit_ratios(frame: np.ndarray, bbox: tuple[int | float, int | float, int | float, int | float]) -> tuple[float, float, float]:
    x1, y1, x2, y2 = map(int, bbox)
    h, w = frame.shape[:2]
    x1, y1 = max(0, x1), max(0, y1)
    x2, y2 = min(w, x2), min(h, y2)
    if x2 <= x1 or y2 <= y1:
        return 0.0, 0.0, 0.0

    crop = frame[y1:y2, x1:x2]
    if crop.shape[0] < 2 or crop.size == 0:
        return 0.0, 0.0, 0.0

    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    dark_mask = (hsv[:, :, 2] < DARK_VALUE_MAX) & (hsv[:, :, 1] < DARK_SATURATION_MAX)
    split_index = dark_mask.shape[0] // 2
    if split_index == 0 or split_index == dark_mask.shape[0]:
        return 0.0, 0.0, 0.0

    upper_ratio = float(np.mean(dark_mask[:split_index, :]))
    lower_ratio = float(np.mean(dark_mask[split_index:, :]))
    overall_ratio = float(np.mean(dark_mask))
    return upper_ratio, lower_ratio, overall_ratio


def is_black_outfit(
    frame: np.ndarray,
    bbox: tuple[int | float, int | float, int | float, int | float],
    *,
    upper_threshold: float = DARK_UPPER_THRESHOLD,
    lower_threshold: float = DARK_LOWER_THRESHOLD,
    overall_threshold: float = DARK_OVERALL_THRESHOLD,
) -> tuple[bool, tuple[float, float, float]]:
    upper_ratio, lower_ratio, overall_ratio = dark_outfit_ratios(frame, bbox)
    is_staff = (
        upper_ratio >= upper_threshold
        and lower_ratio >= lower_threshold
        and overall_ratio >= overall_threshold
    )
    return is_staff, (upper_ratio, lower_ratio, overall_ratio)
