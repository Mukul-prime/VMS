import json
import math
import os
import re
import threading
import time
import traceback
from collections import Counter, deque

os.environ.setdefault("OPENCV_FFMPEG_CAPTURE_OPTIONS", "rtsp_transport;tcp")

import cv2
import numpy as np
from deep_sort_realtime.deepsort_tracker import DeepSort
from django.db import close_old_connections
from ultralytics import YOLO

from Camera.models import CreateCamera
from .models import ObjectDetector, verify_data


try:
    cv2.utils.logging.setLogLevel(cv2.utils.logging.LOG_LEVEL_ERROR)
except Exception:
    pass


CAPTURE_BACKEND = getattr(cv2, "CAP_FFMPEG", 0)
CAPTURE_BUFFER_SIZE = int(os.getenv("CAPTURE_BUFFER_SIZE", "3"))
CAPTURE_RETRY_DELAY_SEC = float(os.getenv("CAPTURE_RETRY_DELAY_SEC", "2.0"))
FRAME_WAIT_SEC = float(os.getenv("FRAME_WAIT_SEC", "0.05"))
READ_FAILURE_LIMIT = int(os.getenv("READ_FAILURE_LIMIT", "20"))
SAVE_INTERVAL_SEC = float(os.getenv("RADAR_SAVE_INTERVAL_SEC", "2.0"))
TRACK_MAX_AGE = int(os.getenv("RADAR_TRACK_MAX_AGE", "40"))
TRACK_STALE_FRAME_TOLERANCE = int(os.getenv("RADAR_TRACK_STALE_FRAMES", "6"))
COUNT_SMOOTH_WINDOW = int(os.getenv("RADAR_COUNT_SMOOTH_WINDOW", "7"))
YOLO_CONFIDENCE = float(os.getenv("RADAR_YOLO_CONF", "0.35"))
YOLO_IOU = float(os.getenv("RADAR_YOLO_IOU", "0.55"))
GLOBAL_ASSOCIATION_MAX_WORLD_DIST = float(os.getenv("GLOBAL_ASSOCIATION_MAX_WORLD_DIST", "0.08"))
GLOBAL_ASSOCIATION_MAX_AGE_SECONDS = float(os.getenv("GLOBAL_ASSOCIATION_MAX_AGE_SECONDS", "2.5"))
GLOBAL_TRACK_TTL_SECONDS = float(os.getenv("GLOBAL_TRACK_TTL_SECONDS", "10"))
GLOBAL_TRACK_MISS_TOLERANCE = int(os.getenv("GLOBAL_TRACK_MISS_TOLERANCE", "3"))
DEFAULT_OBJECT_NAME = os.getenv("DEFAULT_OBJECT_NAME", "chair").strip().lower()

YOLO_TO_DB_ALIASES = {"backpack": "bagpack"}
BLOCKED_CLASSES = {"person"}

ZOOM_MIN = 1.0
ZOOM_MAX = 3.0
ZOOM_STEP = 0.1

camera_flags = {}
camera_workers = {}
camera_zoom_levels = {}
camera_lock = threading.Lock()
zoom_lock = threading.Lock()

shared_object_memory = {}
shared_object_memory_lock = threading.Lock()
global_tracks_lock = threading.Lock()
global_tracks = {}
global_track_seq = 1

_model = None
_model_lock = threading.Lock()


def _canonical_name(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(name).strip().lower())


def _load_camera_homographies():
    raw = os.getenv("CAMERA_HOMOGRAPHIES", "").strip()
    if not raw:
        return {}
    try:
        payload = json.loads(raw)
    except Exception as err:
        print(f"[radar] Invalid CAMERA_HOMOGRAPHIES JSON: {err}", flush=True)
        return {}
    matrices = {}
    for cam_key, matrix in payload.items():
        try:
            h = np.array(matrix, dtype=np.float32)
            if h.shape == (3, 3):
                matrices[int(cam_key)] = h
        except Exception:
            continue
    return matrices


CAMERA_HOMOGRAPHIES = _load_camera_homographies()


def _get_model():
    global _model
    with _model_lock:
        if _model is not None:
            return _model
        candidates = []
        custom_model = os.getenv("YOLO_MODEL", "").strip()
        if custom_model:
            candidates.append(custom_model)
        candidates.extend(["yolov8m.pt", "yolov8s.pt", "yolov8n.pt"])
        for name in candidates:
            try:
                _model = YOLO(name)
                print(f"[radar] Loaded model: {name}", flush=True)
                return _model
            except Exception as error:
                print(f"[radar] Model load failed {name}: {error}", flush=True)
        raise RuntimeError("No YOLO model could be loaded for Radar")


def _wait_or_stop(stop_event, seconds):
    return stop_event.wait(seconds)


def _camera_running(run_key, stop_event):
    return camera_flags.get(str(run_key), False) and not stop_event.is_set()


def _clamp_zoom(value):
    return max(ZOOM_MIN, min(ZOOM_MAX, float(value)))


def set_camera_zoom(cam_id, zoom_value):
    key = str(cam_id)
    with zoom_lock:
        camera_zoom_levels[key] = _clamp_zoom(zoom_value)
        return camera_zoom_levels[key]


def change_camera_zoom(cam_id, delta):
    key = str(cam_id)
    with zoom_lock:
        current = camera_zoom_levels.get(key, ZOOM_MIN)
        current = _clamp_zoom(current + delta)
        camera_zoom_levels[key] = current
        return current


def get_camera_zoom(cam_id):
    with zoom_lock:
        return camera_zoom_levels.get(str(cam_id), ZOOM_MIN)


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


def _project_box_to_world(cam_id, bbox_xyxy):
    h = CAMERA_HOMOGRAPHIES.get(int(cam_id))
    if h is None:
        return None
    x1, y1, x2, y2 = bbox_xyxy
    point = np.array([[[((x1 + x2) / 2.0), y2]]], dtype=np.float32)
    mapped = cv2.perspectiveTransform(point, h)[0][0]
    return float(mapped[0]), float(mapped[1])


def _update_global_unique_count(cam_id, label, world_points, local_count):
    global global_track_seq
    now = time.time()

    if not world_points:
        with shared_object_memory_lock:
            shared_object_memory[label] = {
                "count": int(local_count),
                "last_updated": now,
                "last_camera_id": int(cam_id),
            }
        return int(local_count)

    with global_tracks_lock:
        for track_id in list(global_tracks.keys()):
            if now - global_tracks[track_id]["last_seen"] > max(1.0, GLOBAL_TRACK_TTL_SECONDS):
                del global_tracks[track_id]

        for track in global_tracks.values():
            if track["label"] == label:
                track["visited"] = False

        for wx, wy in world_points:
            best_id = None
            best_dist = None
            for track_id, track in global_tracks.items():
                if track["label"] != label:
                    continue
                age = now - track["last_seen"]
                if age > max(0.3, GLOBAL_ASSOCIATION_MAX_AGE_SECONDS):
                    continue
                twx, twy = track["world_point"]
                dist = math.hypot(wx - twx, wy - twy)
                if dist <= GLOBAL_ASSOCIATION_MAX_WORLD_DIST and (best_dist is None or dist < best_dist):
                    best_id = track_id
                    best_dist = dist

            if best_id is None:
                best_id = global_track_seq
                global_track_seq += 1
                global_tracks[best_id] = {
                    "label": label,
                    "world_point": (wx, wy),
                    "last_seen": now,
                    "visited": True,
                    "miss_cycles": 0,
                }
            else:
                prev_x, prev_y = global_tracks[best_id]["world_point"]
                global_tracks[best_id]["world_point"] = (0.7 * prev_x + 0.3 * wx, 0.7 * prev_y + 0.3 * wy)
                global_tracks[best_id]["last_seen"] = now
                global_tracks[best_id]["visited"] = True
                global_tracks[best_id]["miss_cycles"] = 0

        for track in global_tracks.values():
            if track["label"] != label or track.get("visited"):
                continue
            age = now - track["last_seen"]
            if age <= max(0.3, GLOBAL_ASSOCIATION_MAX_AGE_SECONDS):
                track["miss_cycles"] = track.get("miss_cycles", 0) + 1

        active = 0
        for track in global_tracks.values():
            if track["label"] != label:
                continue
            if track.get("visited"):
                active += 1
                continue
            age = now - track["last_seen"]
            if age <= max(0.3, GLOBAL_ASSOCIATION_MAX_AGE_SECONDS) and track.get("miss_cycles", 0) <= max(
                1, GLOBAL_TRACK_MISS_TOLERANCE
            ):
                active += 1

        with shared_object_memory_lock:
            shared_object_memory[label] = {
                "count": int(active),
                "last_updated": now,
                "last_camera_id": int(cam_id),
            }
        return int(active)


def _draw_tracks(frame, tracks_to_draw):
    for item in tracks_to_draw:
        x1, y1, x2, y2 = item["bbox"]
        label = item["label"]
        tid = item["track_id"]
        cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
        cv2.putText(
            frame,
            f"{label} #{tid}",
            (x1, max(20, y1 - 8)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.55,
            (0, 255, 0),
            2,
        )


def runner(rtsp_url, cam_id, target_object_name=None, session_key=None):
    cam_key = str(cam_id).strip()
    target_label = _canonical_name(target_object_name or DEFAULT_OBJECT_NAME)
    if not target_label:
        target_label = DEFAULT_OBJECT_NAME
    run_key = str(session_key).strip() if session_key else f"{cam_key}:{target_label}"

    db_obj_map = {_canonical_name(obj.Name): obj for obj in ObjectDetector.objects.all()}
    if target_label not in db_obj_map:
        print(f"[radar] Object '{target_label}' not found in DB", flush=True)
        return

    if not rtsp_url:
        cam_row = CreateCamera.objects.filter(Cam_id=cam_key).first()
        if cam_row is None:
            print(f"[radar] Camera {cam_key} not found in DB", flush=True)
            return
        rtsp_url = cam_row.rstp_url

    with camera_lock:
        if camera_workers.get(run_key):
            print(f"[radar] Session {run_key} already running", flush=True)
            return
        stop_event = threading.Event()
        camera_flags[run_key] = True
        camera_workers[run_key] = stop_event
    set_camera_zoom(cam_key, ZOOM_MIN)

    model = _get_model()
    tracker = DeepSort(max_age=TRACK_MAX_AGE)
    latest_frame = None
    latest_frame_id = 0
    latest_tracks = []
    smoothed_count = 0
    frame_lock = threading.Lock()

    def capture():
        nonlocal latest_frame, latest_frame_id
        while _camera_running(run_key, stop_event):
            cap = None
            try:
                cap = _create_capture(rtsp_url)
                read_failures = 0
                while _camera_running(run_key, stop_event):
                    ok, frame = cap.read()
                    if not ok or frame is None:
                        read_failures += 1
                        if read_failures >= READ_FAILURE_LIMIT:
                            break
                        _wait_or_stop(stop_event, FRAME_WAIT_SEC)
                        continue
                    read_failures = 0
                    with frame_lock:
                        latest_frame = frame.copy()
                        latest_frame_id += 1
            except Exception as exc:
                print(f"[radar] capture error cam={cam_key}: {exc}", flush=True)
                traceback.print_exc()
            finally:
                if cap is not None:
                    cap.release()
            if _camera_running(run_key, stop_event):
                _wait_or_stop(stop_event, CAPTURE_RETRY_DELAY_SEC)

    def detect():
        nonlocal latest_frame_id, latest_tracks, smoothed_count
        last_frame_id = 0
        last_save = 0.0
        count_history = deque(maxlen=max(3, COUNT_SMOOTH_WINDOW))

        while _camera_running(run_key, stop_event):
            try:
                with frame_lock:
                    frame_id = latest_frame_id
                    frame = None if latest_frame is None else latest_frame.copy()
                if frame is None or frame_id == last_frame_id:
                    _wait_or_stop(stop_event, FRAME_WAIT_SEC)
                    continue
                last_frame_id = frame_id

                result = model(frame, conf=YOLO_CONFIDENCE, iou=YOLO_IOU, verbose=False)[0]
                detections = []
                for box in result.boxes:
                    conf = float(box.conf[0])
                    cls = int(box.cls[0])
                    raw_label = str(model.names[cls]).lower()
                    label = _canonical_name(YOLO_TO_DB_ALIASES.get(raw_label, raw_label))
                    if label in BLOCKED_CLASSES or label != target_label:
                        continue
                    x1, y1, x2, y2 = map(int, box.xyxy[0])
                    width = max(1, x2 - x1)
                    height = max(1, y2 - y1)
                    detections.append(([x1, y1, width, height], conf, label))

                tracks = tracker.update_tracks(detections, frame=frame)
                track_rows = []
                world_points = []
                for track in tracks:
                    if not track.is_confirmed():
                        continue
                    if track.time_since_update > TRACK_STALE_FRAME_TOLERANCE:
                        continue
                    ltrb = track.to_ltrb()
                    x1, y1, x2, y2 = map(int, ltrb)
                    x1 = max(0, x1)
                    y1 = max(0, y1)
                    x2 = max(x1 + 1, x2)
                    y2 = max(y1 + 1, y2)
                    bbox = (x1, y1, x2, y2)
                    track_rows.append({"track_id": int(track.track_id), "bbox": bbox, "label": target_label})
                    wp = _project_box_to_world(cam_key, bbox)
                    if wp is not None:
                        world_points.append(wp)

                local_count = len({item["track_id"] for item in track_rows})
                unique_count = _update_global_unique_count(cam_key, target_label, world_points, local_count)
                count_history.append(unique_count)
                sorted_counts = sorted(count_history)
                smoothed_count = sorted_counts[len(sorted_counts) // 2]
                with frame_lock:
                    latest_tracks = track_rows

                if time.time() - last_save >= SAVE_INTERVAL_SEC:
                    last_save = time.time()
                    close_old_connections()
                    cam = CreateCamera.objects.filter(Cam_id=cam_key).first()
                    obj_ref = db_obj_map.get(target_label)
                    if cam is not None and obj_ref is not None:
                        verify_data.objects.update_or_create(
                            ObjectRef=obj_ref,
                            CamRef=cam,
                            defaults={"Verified": smoothed_count > 0, "count": int(smoothed_count)},
                        )

                print(f"[radar] cam={cam_key} {target_label}={smoothed_count}", flush=True)
            except Exception as exc:
                print(f"[radar] detect error cam={cam_key}: {exc}", flush=True)
                traceback.print_exc()
                _wait_or_stop(stop_event, FRAME_WAIT_SEC)

    def display():
        nonlocal latest_frame_id
        safe_object = target_label if target_label else "object"
        window_name = f"Radar Cam {cam_key} - {safe_object} ({run_key})"
        last_frame_id = 0
        window_ready = False
        try:
            cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)
            window_ready = True
        except Exception as exc:
            print(f"[radar] window disabled cam={cam_key}: {exc}", flush=True)

        while _camera_running(run_key, stop_event):
            with frame_lock:
                frame_id = latest_frame_id
                frame = None if latest_frame is None else latest_frame.copy()
                tracks_to_draw = list(latest_tracks)
                count_now = int(smoothed_count)

            if frame is None or frame_id == last_frame_id:
                _wait_or_stop(stop_event, FRAME_WAIT_SEC)
                continue
            last_frame_id = frame_id
            if not window_ready:
                _wait_or_stop(stop_event, FRAME_WAIT_SEC)
                continue

            zoom_level = get_camera_zoom(cam_key)
            frame = _apply_zoom(frame, zoom_level)
            _draw_tracks(frame, tracks_to_draw)
            cv2.putText(frame, f"{target_label}: {count_now}", (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 255), 2)
            cv2.putText(frame, f"Zoom: {zoom_level:.1f}x", (20, 80), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (255, 255, 0), 2)

            cv2.imshow(window_name, frame)
            key = cv2.waitKey(1) & 0xFF
            if key in (ord("+"), ord("=")):
                change_camera_zoom(cam_key, ZOOM_STEP)
            elif key in (ord("-"), ord("_")):
                change_camera_zoom(cam_key, -ZOOM_STEP)
            elif key == ord("0"):
                set_camera_zoom(cam_key, ZOOM_MIN)
            elif key == 27:
                stop_event.set()
                break

        if window_ready:
            cv2.destroyWindow(window_name)

    print(f"[radar] started session={run_key} cam={cam_key} object={target_label}", flush=True)
    threads = [
        threading.Thread(target=capture, daemon=True, name=f"radar-{cam_key}-capture"),
        threading.Thread(target=detect, daemon=True, name=f"radar-{cam_key}-detect"),
        threading.Thread(target=display, daemon=True, name=f"radar-{cam_key}-display"),
    ]
    for t in threads:
        t.start()

    try:
        while _camera_running(run_key, stop_event):
            time.sleep(0.2)
    finally:
        stop_event.set()
        with camera_lock:
            camera_flags[run_key] = False
            camera_workers.pop(run_key, None)
        with zoom_lock:
            camera_zoom_levels.pop(cam_key, None)
        for t in threads:
            t.join(timeout=2.0)
        print(f"[radar] stopped session={run_key} cam={cam_key}", flush=True)


def stop_runner(session_key):
    run_key = str(session_key).strip()
    with camera_lock:
        stop_event = camera_workers.get(run_key)
    if stop_event is None:
        return False
    stop_event.set()
    return True
