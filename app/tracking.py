"""Appearance-based person tracking across cameras.

Matches people by visual similarity (clothing color, body shape) to prevent
duplicate counting across cameras. Automatically detects staff by black uniforms.
"""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import NamedTuple

import cv2
import numpy as np
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import EventRecord
from pipeline.staff_classifier import is_black_outfit

logger = logging.getLogger(__name__)


class PersonSignature(NamedTuple):
    """Visual signature of a person for matching across cameras."""
    color_histogram: tuple  # Dominant colors in HSV space
    body_shape: tuple      # Aspect ratio, size
    timestamp: float       # When detected
    camera_id: str         # Camera where detected
    bbox: tuple            # Bounding box (x1, y1, x2, y2)


class PersonTracker:
    """Track people across cameras using visual appearance matching.
    
    Features:
    - Matches people by clothing color and body shape
    - Detects staff by black uniform color
    - Prevents duplicate counting across cameras
    - Groups detections by person ID across time and space
    """
    
    def __init__(self, color_threshold: float = 0.75, time_threshold_seconds: int = 30):
        """
        Args:
            color_threshold: Similarity threshold for color matching (0-1)
            time_threshold_seconds: Max time gap between detections of same person
        """
        self.color_threshold = color_threshold
        self.time_threshold_seconds = time_threshold_seconds
        self.person_signatures: dict[str, PersonSignature] = {}  # person_id -> latest signature
        self.person_to_visitor_id: dict[str, str] = {}  # person_id -> visitor_id
        self.person_staff_status: dict[str, bool] = {}  # person_id -> is_staff
        
    def extract_person_signature(
        self,
        frame: np.ndarray,
        bbox: tuple,
        camera_id: str,
        timestamp: datetime,
    ) -> PersonSignature:
        """Extract visual signature from person detection in frame.
        
        Args:
            frame: Video frame (BGR)
            bbox: Bounding box (x1, y1, x2, y2) in frame coordinates
            camera_id: Camera ID
            timestamp: Detection timestamp
            
        Returns:
            PersonSignature containing visual features
        """
        x1, y1, x2, y2 = [int(v) for v in bbox]
        
        # Crop person from frame
        person_crop = frame[max(0, y1):min(frame.shape[0], y2),
                           max(0, x1):min(frame.shape[1], x2)]
        
        if person_crop.size == 0:
            return PersonSignature(
                color_histogram=(),
                body_shape=(0, 0),
                timestamp=timestamp.timestamp(),
                camera_id=camera_id,
                bbox=bbox,
            )
        
        # Extract dominant color in HSV (more robust than RGB)
        hsv = cv2.cvtColor(person_crop, cv2.COLOR_BGR2HSV)
        
        # Create histogram for each channel
        hist_h = cv2.calcHist([hsv], [0], None, [8], [0, 180])  # Hue
        hist_s = cv2.calcHist([hsv], [1], None, [8], [0, 256])  # Saturation
        hist_v = cv2.calcHist([hsv], [2], None, [8], [0, 256])  # Value
        
        # Normalize and flatten
        hist_h = cv2.normalize(hist_h, hist_h).flatten()
        hist_s = cv2.normalize(hist_s, hist_s).flatten()
        hist_v = cv2.normalize(hist_v, hist_v).flatten()
        
        color_hist = tuple(np.concatenate([hist_h, hist_s, hist_v]))
        
        # Body shape: aspect ratio and size
        height = y2 - y1
        width = x2 - x1
        aspect_ratio = width / (height + 1e-6)
        size = width * height
        body_shape = (aspect_ratio, size)
        
        return PersonSignature(
            color_histogram=color_hist,
            body_shape=body_shape,
            timestamp=timestamp.timestamp(),
            camera_id=camera_id,
            bbox=bbox,
        )
    
    def is_black_uniform(self, signature: PersonSignature, frame: np.ndarray) -> bool:
        """Check if person is wearing black uniform (staff detection).
        
        Black uniform characteristics:
        - Low saturation (not colorful)
        - Low value/brightness (dark)
        - Covers most of upper body
        
        Args:
            signature: Person signature with bbox
            frame: Original frame
            
        Returns:
            True if appears to be wearing black uniform
        """
        is_staff, _ = is_black_outfit(frame, signature.bbox)
        return is_staff
    
    def calculate_color_similarity(
        self,
        signature1: PersonSignature,
        signature2: PersonSignature,
    ) -> float:
        """Calculate similarity between two person color histograms.
        
        Uses chi-square distance between histograms.
        
        Args:
            signature1: First person signature
            signature2: Second person signature
            
        Returns:
            Similarity score (0-1, higher = more similar)
        """
        if not signature1.color_histogram or not signature2.color_histogram:
            return 0.0
        
        hist1 = np.array(signature1.color_histogram)
        hist2 = np.array(signature2.color_histogram)
        
        # Chi-square distance
        chi_square = cv2.compareHist(
            hist1.reshape(-1, 1).astype(np.float32),
            hist2.reshape(-1, 1).astype(np.float32),
            cv2.HISTCMP_CHISQR,
        )
        
        # Convert distance to similarity (0-1)
        similarity = 1.0 / (1.0 + chi_square)
        return float(similarity)
    
    def calculate_shape_similarity(
        self,
        signature1: PersonSignature,
        signature2: PersonSignature,
    ) -> float:
        """Calculate similarity between two person body shapes.
        
        Args:
            signature1: First person signature
            signature2: Second person signature
            
        Returns:
            Similarity score (0-1, higher = more similar)
        """
        if not signature1.body_shape or not signature2.body_shape:
            return 0.0
        
        ratio1, size1 = signature1.body_shape
        ratio2, size2 = signature2.body_shape
        
        # Aspect ratio similarity (allow 20% variation)
        ratio_diff = abs(ratio1 - ratio2) / (max(ratio1, ratio2) + 1e-6)
        ratio_sim = max(0, 1.0 - ratio_diff)
        
        # Size similarity (allow 30% variation)
        size_diff = abs(size1 - size2) / (max(size1, size2) + 1e-6)
        size_sim = max(0, 1.0 - size_diff)
        
        # Combined shape similarity
        return 0.6 * ratio_sim + 0.4 * size_sim
    
    def match_person_across_cameras(
        self,
        new_signature: PersonSignature,
        frame: np.ndarray,
    ) -> tuple[str | None, float]:
        """Find matching person from previous detections.
        
        Matches by:
        1. Color similarity (weighted 60%)
        2. Body shape similarity (weighted 40%)
        3. Time proximity (must be recent)
        
        Args:
            new_signature: New detection signature
            frame: Frame where detected
            
        Returns:
            Tuple of (matched_person_id or None, confidence score)
        """
        best_match_id = None
        best_confidence = 0.0
        now = datetime.now(timezone.utc).timestamp()
        
        for person_id, stored_sig in self.person_signatures.items():
            # Skip if too much time passed (person left store)
            time_diff = now - stored_sig.timestamp
            if time_diff > self.time_threshold_seconds:
                continue
            
            # Skip if on completely different cameras (very unlikely)
            # unless within 10 seconds (person moving between zones)
            if stored_sig.camera_id != new_signature.camera_id and time_diff > 10:
                continue
            
            # Calculate similarity scores
            color_sim = self.calculate_color_similarity(stored_sig, new_signature)
            shape_sim = self.calculate_shape_similarity(stored_sig, new_signature)
            
            # Combined confidence
            confidence = 0.6 * color_sim + 0.4 * shape_sim
            
            if confidence > best_confidence:
                best_confidence = confidence
                best_match_id = person_id
        
        # Only match if confidence exceeds threshold
        if best_confidence >= self.color_threshold:
            return best_match_id, best_confidence
        
        return None, best_confidence
    
    def update_or_create_person(
        self,
        new_signature: PersonSignature,
        frame: np.ndarray,
        visitor_id: str | None = None,
    ) -> tuple[str, bool, bool]:
        """Update person tracking with new detection.
        
        Args:
            new_signature: New detection signature
            frame: Frame where detected
            visitor_id: Optional existing visitor_id for this detection
            
        Returns:
            Tuple of (person_id, is_new_person, is_staff)
        """
        # Try to match with existing person
        matched_id, confidence = self.match_person_across_cameras(new_signature, frame)
        
        if matched_id:
            # Update existing person's latest signature
            self.person_signatures[matched_id] = new_signature
            is_staff = self.is_black_uniform(new_signature, frame)
            self.person_staff_status[matched_id] = is_staff
            return matched_id, False, is_staff
        
        # New person detected - create unique ID
        person_id = self._generate_person_id(new_signature)
        self.person_signatures[person_id] = new_signature
        
        if visitor_id:
            self.person_to_visitor_id[person_id] = visitor_id
        
        is_staff = self.is_black_uniform(new_signature, frame)
        self.person_staff_status[person_id] = is_staff
        return person_id, True, is_staff
    
    def _generate_person_id(self, signature: PersonSignature) -> str:
        """Generate unique person ID from signature.
        
        Args:
            signature: Person signature
            
        Returns:
            Unique person ID
        """
        hash_input = (
            str(signature.timestamp) +
            signature.camera_id +
            str(signature.body_shape)
        )
        hash_obj = hashlib.md5(hash_input.encode())
        return f"PERSON_{hash_obj.hexdigest()[:8].upper()}"
    
    def get_person_info(self, person_id: str) -> dict | None:
        """Get stored information about a person.
        
        Args:
            person_id: Person ID
            
        Returns:
            Dict with person info or None if not found
        """
        if person_id not in self.person_signatures:
            return None
        
        sig = self.person_signatures[person_id]
        visitor_id = self.person_to_visitor_id.get(person_id)
        
        return {
            "person_id": person_id,
            "visitor_id": visitor_id,
            "last_seen": datetime.fromtimestamp(sig.timestamp, tz=timezone.utc).isoformat(),
            "last_camera": sig.camera_id,
            "bbox": sig.bbox,
        }
    
    def cleanup_old_detections(self) -> int:
        """Remove old person signatures (person left store).
        
        Returns:
            Number of people removed
        """
        now = datetime.now(timezone.utc).timestamp()
        old_ids = [
            pid for pid, sig in self.person_signatures.items()
            if (now - sig.timestamp) > self.time_threshold_seconds
        ]
        
        for pid in old_ids:
            del self.person_signatures[pid]
            self.person_to_visitor_id.pop(pid, None)
            self.person_staff_status.pop(pid, None)
        
        return len(old_ids)
    
    def get_staff_members(self) -> list[dict]:
        """Get all currently detected staff members.
        
        Returns:
            List of staff member info dicts
        """
        staff_list = []
        for person_id, is_staff in self.person_staff_status.items():
            if is_staff and person_id in self.person_signatures:
                sig = self.person_signatures[person_id]
                staff_list.append({
                    "person_id": person_id,
                    "last_seen": datetime.fromtimestamp(sig.timestamp, tz=timezone.utc).isoformat(),
                    "camera": sig.camera_id,
                })
        return staff_list
    
    def get_staff_count(self) -> int:
        """Get count of currently tracked staff members.
        
        Returns:
            Number of active staff members
        """
        staff_count = 0
        for person_id, is_staff in self.person_staff_status.items():
            if is_staff and person_id in self.person_signatures:
                staff_count += 1
        return staff_count


# Global tracker instance
_tracker_instance: PersonTracker | None = None


def get_tracker() -> PersonTracker:
    """Get or create global person tracker instance."""
    global _tracker_instance
    if _tracker_instance is None:
        _tracker_instance = PersonTracker()
    return _tracker_instance


async def enhance_visitor_id_with_appearance(
    session: AsyncSession,
    visitor_id: str,
    camera_id: str,
    frame: np.ndarray,
    bbox: tuple,
) -> tuple[str, bool]:
    """Enhance visitor tracking with appearance-based matching.
    
    Updates visitor_id if person matches existing detection, and detects staff.
    
    Args:
        session: Database session
        visitor_id: Original visitor_id from detection
        camera_id: Camera where detected
        frame: Video frame
        bbox: Person bounding box
        
    Returns:
        Tuple of (final_visitor_id, is_staff)
    """
    tracker = get_tracker()
    timestamp = datetime.now(timezone.utc)
    
    # Extract appearance signature
    signature = tracker.extract_person_signature(frame, bbox, camera_id, timestamp)
    
    # Check if this person was seen before
    person_id, is_new, is_staff = tracker.update_or_create_person(
        signature,
        frame,
        visitor_id=visitor_id,
    )
    
    # If we matched an existing person, use their visitor_id
    if not is_new and person_id in tracker.person_to_visitor_id:
        final_visitor_id = tracker.person_to_visitor_id[person_id]
    else:
        final_visitor_id = visitor_id
        tracker.person_to_visitor_id[person_id] = visitor_id
    
    logger.debug(
        f"Person tracking: camera={camera_id}, visitor={final_visitor_id}, "
        f"is_staff={is_staff}, is_new={is_new}"
    )
    
    return final_visitor_id, is_staff
