from __future__ import annotations

import os
import sys
import threading
import time
from collections import Counter
from pathlib import Path

import cv2
import django
from django.apps import apps
from ultralytics import YOLO


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "IronHeart.settings")
if not apps.ready:
    django.setup()

from Camera.models import CreateCamera


YOLO_MODEL = "yolov8x.pt"
OBJECT_CONFIDENCE = 0.40
PERSON_CONFIDENCE = 0.40
RECONNECT_DELAY_SEC = 2.0

# Person aur animals ko object detector me intentionally skip kiya gaya hai.
EXCLUDED_OBJECT_CLASSES = {
    "person",
    "bird",
    "cat",
    "dog",
    "horse",
    "sheep",
    "cow",
    "elephant",
    "bear",
    "zebra",
    "giraffe",
}


def get_camera_stream(camera_id: int) -> tuple[str, str]:
    camera = (
        CreateCamera.objects.filter(Cam_id=camera_id)
        .values("Cam_name", "rstp_url")
        .first()
    )
    if camera is None:
        raise ValueError(f"Camera ID {camera_id} database me nahi mila.")

    rtsp_url = (camera.get("rstp_url") or "").strip()
    if not rtsp_url:
        raise ValueError(f"Camera ID {camera_id} ka rstp_url empty hai.")

    camera_name = (camera.get("Cam_name") or f"Camera-{camera_id}").strip()
    return camera_name, rtsp_url


def _create_capture(rtsp_url: str) -> cv2.VideoCapture:
    capture = cv2.VideoCapture(rtsp_url)
    capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    if not capture.isOpened():
        capture.release()
        raise RuntimeError(f"RTSP stream open nahi hua: {rtsp_url}")
    return capture


def _summarize_counts(counts: Counter[str]) -> str:
    if not counts:
        return "(none)"
    parts = [
        f"{label}={count}"
        for label, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    ]
    return ", ".join(parts)


def _extract_counts(
    model: YOLO,
    frame,
    confidence: float,
    allowed_labels: set[str] | None = None,
    excluded_labels: set[str] | None = None,
) -> Counter[str]:
    results = model(frame, conf=confidence, verbose=False)[0]
    counts: Counter[str] = Counter()

    for box in results.boxes:
        label_index = int(box.cls[0])
        label = str(model.names[label_index])

        if allowed_labels is not None and label not in allowed_labels:
            continue
        if excluded_labels is not None and label in excluded_labels:
            continue

        counts[label] += 1

    return counts


def _wait_or_stop(stop_event: threading.Event | None, seconds: float) -> bool:
    if stop_event is None:
        time.sleep(seconds)
        return False
    return stop_event.wait(seconds)


def _run_detector(
    detector_name: str,
    camera_id: int,
    rtsp_url: str,
    camera_name: str,
    confidence: float,
    allowed_labels: set[str] | None = None,
    excluded_labels: set[str] | None = None,
    stop_event: threading.Event | None = None,
) -> None:
    model = YOLO(YOLO_MODEL)
    last_signature: tuple[tuple[str, int], ...] | None = None

    print(
        f"[{detector_name}] Camera {camera_id} ({camera_name}) detector start hua.",
        flush=True,
    )

    while stop_event is None or not stop_event.is_set():
        try:
            capture = _create_capture(rtsp_url)
            print(
                f"[{detector_name}] Camera {camera_id} stream connect ho gaya.",
                flush=True,
            )
        except Exception as exc:
            print(
                f"[{detector_name}] Camera {camera_id} stream error: {exc}",
                flush=True,
            )
            if _wait_or_stop(stop_event, RECONNECT_DELAY_SEC):
                return
            continue

        try:
            while stop_event is None or not stop_event.is_set():
                success, frame = capture.read()
                if not success:
                    print(
                        f"[{detector_name}] Camera {camera_id} frame read fail, reconnecting...",
                        flush=True,
                    )
                    break

                counts = _extract_counts(
                    model=model,
                    frame=frame,
                    confidence=confidence,
                    allowed_labels=allowed_labels,
                    excluded_labels=excluded_labels,
                )

                signature = tuple(sorted(counts.items()))
                if signature != last_signature:
                    last_signature = signature
                    total = sum(counts.values())
                    summary = _summarize_counts(counts)
                    print(
                        f"[{detector_name}] Camera {camera_id} detected total={total} | {summary}",
                        flush=True,
                    )
        except Exception as exc:
            print(
                f"[{detector_name}] Camera {camera_id} inference error: {exc}",
                flush=True,
            )
        finally:
            capture.release()

        if _wait_or_stop(stop_event, RECONNECT_DELAY_SEC):
            return


def run_object_detector(
    camera_id: int,
    rtsp_url: str | None = None,
    camera_name: str | None = None,
    stop_event: threading.Event | None = None,
) -> None:
    if rtsp_url is None or camera_name is None:
        camera_name, rtsp_url = get_camera_stream(camera_id)

    _run_detector(
        detector_name="OBJECTS",
        camera_id=camera_id,
        rtsp_url=rtsp_url,
        camera_name=camera_name,
        confidence=OBJECT_CONFIDENCE,
        excluded_labels=EXCLUDED_OBJECT_CLASSES,
        stop_event=stop_event,
    )


def run_person_detector(
    camera_id: int,
    rtsp_url: str | None = None,
    camera_name: str | None = None,
    stop_event: threading.Event | None = None,
) -> None:
    if rtsp_url is None or camera_name is None:
        camera_name, rtsp_url = get_camera_stream(camera_id)

    _run_detector(
        detector_name="PERSON",
        camera_id=camera_id,
        rtsp_url=rtsp_url,
        camera_name=camera_name,
        confidence=PERSON_CONFIDENCE,
        allowed_labels={"person"},
        stop_event=stop_event,
    )

