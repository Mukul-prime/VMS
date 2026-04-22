import os
import threading

import time
import traceback
from collections import deque

os.environ.setdefault("OPENCV_FFMPEG_CAPTURE_OPTIONS", "rtsp_transport;tcp")

import cv2
from deep_sort_realtime.deepsort_tracker import DeepSort
from django.db import close_old_connections
from django.utils.timezone import now
from ultralytics import YOLO

from .models import CreateCamera, Persons


try:
    cv2.utils.logging.setLogLevel(cv2.utils.logging.LOG_LEVEL_ERROR)
except Exception:
    pass


CAPTURE_BACKEND = getattr(cv2, "CAP_FFMPEG", 0)
CAPTURE_BUFFER_SIZE = 3
CAPTURE_RETRY_DELAY_SEC = 2.0
FRAME_WAIT_SEC = 0.05
READ_FAILURE_LIMIT = 20
SAVE_INTERVAL_SEC = 2.0
TRACK_MAX_AGE = 40
PERSON_CONFIDENCE = 0.25
TRACK_STALE_FRAME_TOLERANCE = 6
COUNT_SMOOTH_WINDOW = 7
ZOOM_MIN = 1.0
ZOOM_MAX = 3.0
ZOOM_STEP = 0.1

os.environ.setdefault("OPENCV_FFMPEG_CAPTURE_OPTIONS", "rtsp_transport;tcp")

import cv2
from deep_sort_realtime.deepsort_tracker import DeepSort
from django.db import close_old_connections
from django.utils.timezone import now
from ultralytics import YOLO

from .models import CreateCamera, Persons


try:
    cv2.utils.logging.setLogLevel(cv2.utils.logging.LOG_LEVEL_ERROR)
except Exception:
    pass


CAPTURE_BACKEND = getattr(cv2, "CAP_FFMPEG", 0)
CAPTURE_BUFFER_SIZE = 1
CAPTURE_RETRY_DELAY_SEC = 2.0
FRAME_WAIT_SEC = 0.05
READ_FAILURE_LIMIT = 20
SAVE_INTERVAL_SEC = 2.0
TRACK_MAX_AGE = 40
PERSON_CONFIDENCE = 0.25

camera_flags = {}
camera_zoom_levels = {}
zoom_lock = threading.Lock()


def _wait_or_stop(stop_event, seconds):
    return stop_event.wait(seconds)


def _camera_running(cam_id, stop_event):
    return camera_flags.get(cam_id, False) and not stop_event.is_set()


def _clamp_zoom(zoom_value):
    return max(ZOOM_MIN, min(ZOOM_MAX, float(zoom_value)))


def set_camera_zoom(cam_id, zoom_value):
    with zoom_lock:
        camera_zoom_levels[cam_id] = _clamp_zoom(zoom_value)
        return camera_zoom_levels[cam_id]


def change_camera_zoom(cam_id, delta):
    with zoom_lock:
        current_zoom = camera_zoom_levels.get(cam_id, ZOOM_MIN)
        current_zoom = _clamp_zoom(current_zoom + delta)
        camera_zoom_levels[cam_id] = current_zoom
        return current_zoom


def get_camera_zoom(cam_id):
    with zoom_lock:
        return camera_zoom_levels.get(cam_id, ZOOM_MIN)


def _apply_zoom(frame, zoom_level):
    if zoom_level <= 1.0:
        return frame

    frame_h, frame_w = frame.shape[:2]
    crop_w = int(frame_w / zoom_level)
    crop_h = int(frame_h / zoom_level)
    if crop_w <= 0 or crop_h <= 0:
        return frame

    start_x = (frame_w - crop_w) // 2
    start_y = (frame_h - crop_h) // 2
    end_x = start_x + crop_w
    end_y = start_y + crop_h

    cropped = frame[start_y:end_y, start_x:end_x]
    return cv2.resize(cropped, (frame_w, frame_h), interpolation=cv2.INTER_LINEAR)


def _create_capture(rtsp_url):
    capture = cv2.VideoCapture(rtsp_url, CAPTURE_BACKEND)
    capture.set(cv2.CAP_PROP_BUFFERSIZE, CAPTURE_BUFFER_SIZE)
    if not capture.isOpened():
        capture.release()
        raise RuntimeError(f"RTSP stream open failed: {rtsp_url}")
    return capture


def runner(rtsp_url, cam_id):
    latest_frame = None
    latest_frame_id = 0
    person_ids = []
    frame_lock = threading.Lock()
    stop_event = threading.Event()

    camera_flags[cam_id] = True
    set_camera_zoom(cam_id, ZOOM_MIN)

    yolo = YOLO("yolov8m.pt")
    tracker = DeepSort(max_age=TRACK_MAX_AGE)

    def capture():
        nonlocal latest_frame, latest_frame_id

        while _camera_running(cam_id, stop_event):
            capture_handle = None
            try:
                capture_handle = _create_capture(rtsp_url)
                print(f"[capture] Camera {cam_id} connected", flush=True)
                read_failures = 0

                while _camera_running(cam_id, stop_event):
                    ret, frame = capture_handle.read()
                    if not ret or frame is None:
                        read_failures += 1
                        if read_failures >= READ_FAILURE_LIMIT:
                            print(
                                f"[capture] Camera {cam_id} reconnecting after read failures",
                                flush=True,
                            )
                            break
                        _wait_or_stop(stop_event, FRAME_WAIT_SEC)
                        continue

                    read_failures = 0
                    with frame_lock:
                        latest_frame = frame.copy()
                        latest_frame_id += 1
            except Exception as exc:
                print(f"[capture] Camera {cam_id} error: {exc}", flush=True)
                traceback.print_exc()
            finally:
                if capture_handle is not None:
                    capture_handle.release()

            if _camera_running(cam_id, stop_event):
                _wait_or_stop(stop_event, CAPTURE_RETRY_DELAY_SEC)

    def detect():
        nonlocal latest_frame, latest_frame_id, person_ids

        last_frame_id = 0
        last_save = 0.0
        count_history = deque(maxlen=max(3, COUNT_SMOOTH_WINDOW))

        while _camera_running(cam_id, stop_event):
            try:
                with frame_lock:
                    frame_id = latest_frame_id
                    frame = None if latest_frame is None else latest_frame.copy()

                if frame is None or frame_id == last_frame_id:
                    _wait_or_stop(stop_event, FRAME_WAIT_SEC)
                    continue

                last_frame_id = frame_id
                results = yolo(frame, verbose=False)[0]
                detections = []

                for box in results.boxes:
                    conf = float(box.conf[0])
                    cls = int(box.cls[0])
                    label = str(yolo.names[cls])

                    if label != "person" or conf < PERSON_CONFIDENCE:
                        continue

                    x1, y1, x2, y2 = map(int, box.xyxy[0])
                    width = x2 - x1
                    height = y2 - y1
                    detections.append(([x1, y1, width, height], conf, "person"))

                tracks = tracker.update_tracks(detections, frame=frame)
                current_ids = []

                for track in tracks:
                    # Keep recently updated confirmed tracks to reduce flicker
                    # when a person moves fast or is briefly occluded.
                    if not track.is_confirmed():
                        continue
                    if track.time_since_update > TRACK_STALE_FRAME_TOLERANCE:
                        continue
                    current_ids.append(track.track_id)

                with frame_lock:
                    person_ids = current_ids

                current_count = len(set(current_ids))
                count_history.append(current_count)
                sorted_counts = sorted(count_history)
                smoothed_count = sorted_counts[len(sorted_counts) // 2]
                print(f"[detect] Camera {cam_id} count: {smoothed_count}", flush=True)

                #  SAVE LOGIC (MERGED)
                if time.time() - last_save >= SAVE_INTERVAL_SEC:
                    last_save = time.time()

                    today = now().date()
                    close_old_connections()

                    cam = CreateCamera.objects.filter(Cam_id=cam_id).first()
                    if cam is None:
                        print(f"[detect] Camera {cam_id} missing in database", flush=True)
                        continue
                    obj, created = Persons.objects.get_or_create(
                        Cam_ids=cam,
                        date=today,
                        defaults={"count": smoothed_count, "previous": 0}
                    )

                    if not created:
                        if obj.count != smoothed_count:
                            obj.previous = obj.count
                            obj.count = smoothed_count
                            obj.save(update_fields=["previous", "count"])

                    print(
                        (
                            f"[SAVE] Cam {cam_id} | Count={obj.count} | "
                            f"Previous={obj.previous} | Created={created}"
                        ),
                        flush=True,
                    )

            except Exception as exc:
                print(f"[detect] Camera {cam_id} error: {exc}", flush=True)
                traceback.print_exc()
                _wait_or_stop(stop_event, FRAME_WAIT_SEC)

    def display():
        nonlocal latest_frame, latest_frame_id, person_ids

        window_name = f"Camera {cam_id}"
        last_frame_id = 0
        window_ready = False

        try:
            cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)
            window_ready = True
        except Exception as exc:
            print(f"[display] Camera {cam_id} window disabled: {exc}", flush=True)

        while _camera_running(cam_id, stop_event):
            with frame_lock:
                frame_id = latest_frame_id
                frame = None if latest_frame is None else latest_frame.copy()
                current_ids = list(set(person_ids))

            if frame is None or frame_id == last_frame_id:
                _wait_or_stop(stop_event, FRAME_WAIT_SEC)
                continue

            last_frame_id = frame_id

            if not window_ready:
                _wait_or_stop(stop_event, FRAME_WAIT_SEC)
                continue

            cv2.putText(
                frame,
                f"Persons: {len(current_ids)}",
                (20, 40),
                cv2.FONT_HERSHEY_SIMPLEX,
                1,
                (0, 255, 255),
                2,
            )
            zoom_level = get_camera_zoom(cam_id)
            frame = _apply_zoom(frame, zoom_level)
            cv2.putText(
                frame,
                f"Zoom: {zoom_level:.1f}x",
                (20, 80),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.9,
                (255, 255, 0),
                2,
            )

            cv2.imshow(window_name, frame)
            key = cv2.waitKey(1) & 0xFF
            if key in (ord("+"), ord("=")):
                changed_zoom = change_camera_zoom(cam_id, ZOOM_STEP)
                print(f"[display] Camera {cam_id} zoom: {changed_zoom:.1f}x", flush=True)
            elif key in (ord("-"), ord("_")):
                changed_zoom = change_camera_zoom(cam_id, -ZOOM_STEP)
                print(f"[display] Camera {cam_id} zoom: {changed_zoom:.1f}x", flush=True)
            elif key == ord("0"):
                changed_zoom = set_camera_zoom(cam_id, ZOOM_MIN)
                print(f"[display] Camera {cam_id} zoom reset: {changed_zoom:.1f}x", flush=True)
            elif key == 27:
                camera_flags[cam_id] = False
                stop_event.set()
                break

        if window_ready:
            cv2.destroyWindow(window_name)

    print(f"[runner] Camera {cam_id} started", flush=True)

    threads = [
        threading.Thread(target=capture, daemon=True, name=f"camera-{cam_id}-capture"),
        threading.Thread(target=detect, daemon=True, name=f"camera-{cam_id}-detect"),
        threading.Thread(target=display, daemon=True, name=f"camera-{cam_id}-display"),
    ]

    for thread in threads:
        thread.start()

    try:
        while _camera_running(cam_id, stop_event):
            time.sleep(0.2)
    finally:
        camera_flags[cam_id] = False
        stop_event.set()
        with zoom_lock:
            camera_zoom_levels.pop(cam_id, None)
        for thread in threads:
            thread.join(timeout=2.0)
        print(f"[runner] Camera {cam_id} stopped", flush=True)
