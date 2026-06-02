"""Live camera feed with YOLO detection."""
from __future__ import annotations

import asyncio
from pathlib import Path

import cv2
import numpy as np
from ultralytics import YOLO


class CameraFeed:
    """Handles video capture and YOLO detection."""

    def __init__(self, video_path: str, model_path: str = "yolov8n.pt"):
        """Initialize camera feed with video file.
        
        Args:
            video_path: Path to video file
            model_path: Path to YOLO model
        """
        self.video_path = video_path
        self.cap = cv2.VideoCapture(video_path)
        self.model = YOLO(model_path)
        self.current_frame = None
        self.detections = []

    def is_available(self) -> bool:
        """Check if video is available."""
        return self.cap.isOpened()

    def get_frame_with_detections(self) -> tuple[bytes, int, int, list]:
        """Get next frame with YOLO detections.
        
        Returns:
            Tuple of (frame_bytes, width, height, detections)
        """
        ret, frame = self.cap.read()
        if not ret:
            # Loop video
            self.cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
            ret, frame = self.cap.read()
            if not ret:
                return None, 0, 0, []

        # Resize for faster processing
        height, width = frame.shape[:2]
        scale = 640 / max(height, width)
        new_h, new_w = int(height * scale), int(width * scale)
        frame_resized = cv2.resize(frame, (new_w, new_h))

        # Run YOLO detection
        results = self.model(frame_resized, verbose=False)
        detections = []

        # Draw detections
        for result in results:
            for box in result.boxes:
                x1, y1, x2, y2 = map(int, box.xyxy[0].tolist())
                conf = float(box.conf[0])
                cls_id = int(box.cls[0])
                cls_name = result.names[cls_id]

                # Draw bounding box
                cv2.rectangle(frame_resized, (x1, y1), (x2, y2), (0, 255, 0), 2)
                cv2.putText(
                    frame_resized,
                    f"{cls_name} {conf:.2f}",
                    (x1, y1 - 10),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.5,
                    (0, 255, 0),
                    2,
                )

                detections.append(
                    {
                        "class": cls_name,
                        "confidence": conf,
                        "bbox": [x1, y1, x2, y2],
                    }
                )

        self.detections = detections

        # Encode frame to JPEG
        _, buffer = cv2.imencode(".jpg", frame_resized)
        frame_bytes = buffer.tobytes()

        return frame_bytes, new_w, new_h, detections

    def close(self) -> None:
        """Close video capture."""
        self.cap.release()


class CameraManager:
    """Manages multiple camera feeds."""

    def __init__(self, data_dir: str = "data/CCTV", model_path: str = "yolov8n.pt"):
        """Initialize camera manager.
        
        Args:
            data_dir: Directory containing video files (default: data/CCTV)
            model_path: Path to YOLO model (default: yolov8n.pt)
        """
        self.data_dir = Path(data_dir)
        self.model_path = model_path
        self.cameras: dict[str, CameraFeed] = {}
        self._load_cameras()

    def _load_cameras(self) -> None:
        """Load all available video files."""
        if not self.data_dir.exists():
            return

        for video_file in sorted(self.data_dir.glob("*.mp4")):
            camera_name = video_file.stem
            try:
                feed = CameraFeed(str(video_file), self.model_path)
                if feed.is_available():
                    self.cameras[camera_name] = feed
            except Exception as e:
                print(f"Failed to load camera {camera_name}: {e}")

    def get_available_cameras(self) -> list[str]:
        """Get list of available cameras."""
        return list(self.cameras.keys())

    def get_frame(self, camera_name: str) -> tuple[bytes, int, int, list] | None:
        """Get frame from specific camera.
        
        Args:
            camera_name: Camera identifier
            
        Returns:
            Tuple of (frame_bytes, width, height, detections) or None
        """
        if camera_name not in self.cameras:
            return None
        return self.cameras[camera_name].get_frame_with_detections()

    def get_detections(self, camera_name: str) -> list:
        """Get latest detections for camera.
        
        Args:
            camera_name: Camera identifier
            
        Returns:
            List of detections
        """
        if camera_name not in self.cameras:
            return []
        return self.cameras[camera_name].detections

    def close_all(self) -> None:
        """Close all camera feeds."""
        for feed in self.cameras.values():
            feed.close()
