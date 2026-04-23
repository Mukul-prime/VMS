import cv2
import os
import re
import json
import math
import time
import threading
import numpy as np
from datetime import timedelta
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from ultralytics import YOLO
from django.db import close_old_connections
from django.utils import timezone

from .models import ObjectDetector, verify_data
from Camera.models import CreateCamera


running_cameras = {}
active_camera_runs = {}
active_camera_runs_lock = threading.Lock()

global_tracks_lock = threading.Lock()
global_tracks = {}
global_track_seq = 1

shared_object_memory = {}
shared_object_memory_lock = threading.Lock()

PERFORMANCE_MODE = os.getenv("PERFORMANCE_MODE", "accurate").strip().lower()
LIGHTWEIGHT_MODE = os.getenv("LIGHTWEIGHT_MODE", "1").strip().lower() in {"1", "true", "yes", "on"}

if PERFORMANCE_MODE == "accurate":
    default_candidates = ["yolov8x.pt", "yolov8l.pt", "yolov8m.pt"]
    default_imgsz = 1280
    default_conf = 0.25
    default_interval = 2
else:
    default_candidates = ["yolov8n.pt", "yolov8s.pt", "yolov8m.pt"]
    default_imgsz = 640
    default_conf = 0.45
    default_interval = 4

custom_model = os.getenv("YOLO_MODEL", "").strip()
MODEL_CANDIDATES = [custom_model] + default_candidates if custom_model else default_candidates

_loaded_model = None
for model_name in MODEL_CANDIDATES:
    try:
        _loaded_model = YOLO(model_name)
        print(f"[MODEL] Loaded {model_name}")
        break
    except Exception as model_error:
        print(f"[MODEL ERROR] {model_name}: {model_error}")

if _loaded_model is None:
    raise RuntimeError("No YOLO model could be loaded.")

model = _loaded_model
BLOCKED_CLASSES = {"person"}
YOLO_TO_DB_ALIASES = {"backpack": "bagpack"}

YOLO_IMGSZ = int(os.getenv("YOLO_IMGSZ", str(default_imgsz)))
YOLO_CONF = float(os.getenv("YOLO_CONF", str(default_conf)))
YOLO_IOU = float(os.getenv("YOLO_IOU", "0.55"))
YOLO_AUGMENT = os.getenv("YOLO_AUGMENT", "1" if PERFORMANCE_MODE == "accurate" else "0").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}
DETECTION_INTERVAL_SECONDS = int(os.getenv("DETECTION_INTERVAL_SECONDS", str(default_interval)))
INFERENCE_WORKERS = int(os.getenv("INFERENCE_WORKERS", "1"))
DB_REFRESH_INTERVAL = int(os.getenv("DB_REFRESH_INTERVAL", "5"))
DB_SAVE_INTERVAL_SECONDS = int(os.getenv("DB_SAVE_INTERVAL_SECONDS", str(default_interval)))
MAX_DRAW_BOXES = int(os.getenv("MAX_DRAW_BOXES", "20"))
CAPTURE_BUFFER_SIZE = int(os.getenv("CAPTURE_BUFFER_SIZE", "6"))
MAX_CORRUPTED_FRAMES = int(os.getenv("MAX_CORRUPTED_FRAMES", "6"))
VERIFY_DATA_RETENTION_HOURS = int(os.getenv("VERIFY_DATA_RETENTION_HOURS", "24"))
VERIFY_DATA_CLEANUP_INTERVAL_SECONDS = int(os.getenv("VERIFY_DATA_CLEANUP_INTERVAL_SECONDS", "600"))

GLOBAL_ASSOCIATION_MAX_WORLD_DIST = float(os.getenv("GLOBAL_ASSOCIATION_MAX_WORLD_DIST", "0.08"))
GLOBAL_ASSOCIATION_MAX_AGE_SECONDS = float(os.getenv("GLOBAL_ASSOCIATION_MAX_AGE_SECONDS", "2.5"))
GLOBAL_TRACK_TTL_SECONDS = float(os.getenv("GLOBAL_TRACK_TTL_SECONDS", "10"))
GLOBAL_TRACK_MISS_TOLERANCE = int(os.getenv("GLOBAL_TRACK_MISS_TOLERANCE", "3"))

if LIGHTWEIGHT_MODE:
    YOLO_IMGSZ = min(YOLO_IMGSZ, 640)
    YOLO_CONF = max(YOLO_CONF, 0.35)
    DETECTION_INTERVAL_SECONDS = max(DETECTION_INTERVAL_SECONDS, 3)
    YOLO_AUGMENT = False
    MAX_DRAW_BOXES = min(MAX_DRAW_BOXES, 15)


def _load_camera_homographies():
    raw = os.getenv("CAMERA_HOMOGRAPHIES", "").strip()
    if not raw:
        return {}
    try:
        payload = json.loads(raw)
    except Exception as err:
        print(f"[CALIBRATION ERROR] Invalid CAMERA_HOMOGRAPHIES JSON: {err}")
        return {}

    matrices = {}
    for cam_key, matrix in payload.items():
        try:
            cam_num = int(cam_key)
            h = np.array(matrix, dtype=np.float32)
            if h.shape == (3, 3):
                matrices[cam_num] = h
        except Exception:
            continue
    return matrices


CAMERA_HOMOGRAPHIES = _load_camera_homographies()


def _canonical_name(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(name).strip().lower())


def _load_db_objects():
    db_objects = {}
    for obj in ObjectDetector.objects.all():
        normalized = _canonical_name(obj.Name)
        if not normalized or normalized in BLOCKED_CLASSES:
            continue
        db_objects.setdefault(normalized, obj)
    return db_objects


def _normalize_rtsp_url(rtsp_url: str) -> str:
    if not rtsp_url:
        return rtsp_url
    if "rtsp_transport=" in rtsp_url:
        return rtsp_url
    sep = "&" if "?" in rtsp_url else "?"
    return f"{rtsp_url}{sep}rtsp_transport=tcp"


def _open_camera_stream(rtsp_url: str):
    os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "rtsp_transport;tcp"
    url = _normalize_rtsp_url(rtsp_url)
    cap = cv2.VideoCapture(url, cv2.CAP_FFMPEG)
    cap.set(cv2.CAP_PROP_BUFFERSIZE, max(1, CAPTURE_BUFFER_SIZE))
    return cap


def _is_corrupted_frame(frame):
    if frame is None or frame.size == 0:
        return True
    if len(frame.shape) != 3 or frame.shape[2] != 3:
        return True
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    std_val = float(np.std(gray))
    mean_val = float(np.mean(gray))
    if std_val < 4.0:
        return True
    if mean_val <= 2.0 or mean_val >= 253.0:
        return True
    return False


def _run_inference(frame_small, target_label):
    boxes = []
    h, w = frame_small.shape[:2]
    results = model(
        frame_small,
        conf=YOLO_CONF,
        iou=YOLO_IOU,
        imgsz=YOLO_IMGSZ,
        augment=YOLO_AUGMENT,
        verbose=False,
    )
    for r in results:
        if r.boxes is None:
            continue
        for box in r.boxes:
            cls_id = int(box.cls[0])
            raw_label = model.names[cls_id].lower()
            label = _canonical_name(YOLO_TO_DB_ALIASES.get(raw_label, raw_label))
            if label in BLOCKED_CLASSES or label != target_label:
                continue
            x1, y1, x2, y2 = box.xyxy[0].tolist()
            boxes.append(
                {
                    "label": label,
                    "x1": max(0.0, min(1.0, x1 / w)),
                    "y1": max(0.0, min(1.0, y1 / h)),
                    "x2": max(0.0, min(1.0, x2 / w)),
                    "y2": max(0.0, min(1.0, y2 / h)),
                    "conf": float(box.conf[0]),
                }
            )
    return boxes


def _draw_boxes(frame, boxes):
    if not boxes:
        return
    frame_h, frame_w = frame.shape[:2]
    for item in boxes[:max(1, MAX_DRAW_BOXES)]:
        x1 = int(item["x1"] * frame_w)
        y1 = int(item["y1"] * frame_h)
        x2 = int(item["x2"] * frame_w)
        y2 = int(item["y2"] * frame_h)
        label = item.get("label", "object")
        cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
        cv2.putText(frame, label, (x1, max(20, y1 - 8)), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)


def _project_box_to_world(cam_id, box):
    h = CAMERA_HOMOGRAPHIES.get(int(cam_id))
    if h is None:
        return None
    point = np.array([[[((box["x1"] + box["x2"]) / 2.0), box["y2"]]]], dtype=np.float32)
    mapped = cv2.perspectiveTransform(point, h)[0][0]
    return float(mapped[0]), float(mapped[1])


def _get_shared_object_count(label):
    with shared_object_memory_lock:
        payload = shared_object_memory.get(label)
        if not payload:
            return 0
        return int(payload.get("count", 0))


def _update_global_unique_count(cam_id, label, boxes):
    global global_track_seq
    now = time.time()
    world_points = []
    for box in boxes:
        if box.get("label") != label:
            continue
        point = _project_box_to_world(cam_id, box)
        if point is not None:
            world_points.append(point)

    if not world_points:
        local_count = len([box for box in boxes if box.get("label") == label])
        with shared_object_memory_lock:
            shared_object_memory[label] = {
                "count": int(local_count),
                "last_updated": now,
                "last_camera_id": int(cam_id),
            }
        return local_count

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
                    best_dist = dist
                    best_id = track_id

            if best_id is None:
                best_id = global_track_seq
                global_track_seq += 1
                global_tracks[best_id] = {
                    "label": label,
                    "world_point": (wx, wy),
                    "last_seen": now,
                    "cameras": {int(cam_id)},
                    "visited": True,
                    "miss_cycles": 0,
                }
            else:
                prev_x, prev_y = global_tracks[best_id]["world_point"]
                global_tracks[best_id]["world_point"] = (0.7 * prev_x + 0.3 * wx, 0.7 * prev_y + 0.3 * wy)
                global_tracks[best_id]["last_seen"] = now
                global_tracks[best_id]["cameras"].add(int(cam_id))
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
        return active


def run_camera_detection(cam_id, stop_event, target_object_name=None):
    requested_label = _canonical_name(target_object_name) if target_object_name else ""
    requested_run = (int(cam_id), requested_label)

    with active_camera_runs_lock:
        if requested_run in active_camera_runs:
            print(f"[REJECTED] Camera/object run already active: {requested_run}")
            return
        active_camera_runs[requested_run] = True

    cam = CreateCamera.objects.filter(Cam_id=cam_id).first()
    if not cam:
        print(f"[ERROR] Camera {cam_id} not found in DB")
        with active_camera_runs_lock:
            active_camera_runs.pop(requested_run, None)
        return

    target_label = _canonical_name(target_object_name) if target_object_name else ""
    db_objects = _load_db_objects()
    if not target_label or target_label not in set(db_objects.keys()):
        print(f"[ERROR] Requested object '{target_object_name}' not found in DB")
        with active_camera_runs_lock:
            active_camera_runs.pop(requested_run, None)
        return

    cap = _open_camera_stream(cam.rstp_url)
    if not cap.isOpened():
        print(f"[ERROR] Camera {cam_id} not opened")
        with active_camera_runs_lock:
            active_camera_runs.pop(requested_run, None)
        return

    window_name = f"Camera {cam_id}"
    cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(window_name, 1280, 720)

    executor = ThreadPoolExecutor(max_workers=max(1, INFERENCE_WORKERS))
    inference_future = None
    next_detection_at = time.time()
    last_boxes = []
    last_count = 0
    last_db_save = 0
    last_db_refresh = 0
    last_cleanup_at = 0
    corrupted_frames = 0

    while not stop_event.is_set():
        ret, frame = cap.read()
        if not ret or frame is None:
            cap.release()
            if stop_event.wait(1):
                break
            cap = _open_camera_stream(cam.rstp_url)
            continue

        if _is_corrupted_frame(frame):
            corrupted_frames += 1
            if corrupted_frames >= max(1, MAX_CORRUPTED_FRAMES):
                cap.release()
                if stop_event.wait(1):
                    break
                cap = _open_camera_stream(cam.rstp_url)
                corrupted_frames = 0
            continue
        corrupted_frames = 0

        if time.time() - last_db_refresh >= DB_REFRESH_INTERVAL:
            db_objects = _load_db_objects()
            if target_label not in set(db_objects.keys()):
                print(f"[STOP] Target object '{target_label}' removed from DB")
                break
            last_db_refresh = time.time()

        if time.time() - last_cleanup_at >= max(60, VERIFY_DATA_CLEANUP_INTERVAL_SECONDS):
            cutoff = timezone.now() - timedelta(hours=max(1, VERIFY_DATA_RETENTION_HOURS))
            verify_data.objects.filter(updated_at__lt=cutoff).delete()
            last_cleanup_at = time.time()

        if inference_future is None and time.time() >= next_detection_at:
            inference_future = executor.submit(_run_inference, frame, target_label)
            next_detection_at = time.time() + max(1, DETECTION_INTERVAL_SECONDS)

        if inference_future is not None and inference_future.done():
            try:
                last_boxes = inference_future.result()
            except Exception as infer_error:
                print(f"[INFERENCE ERROR] {infer_error}")
                last_boxes = []
            inference_future = None

            _update_global_unique_count(cam_id, target_label, last_boxes)
            last_count = _get_shared_object_count(target_label)
            print(f"[GLOBAL SHARED COUNT] {target_label}: {last_count}")

        if time.time() - last_db_save >= max(1, DB_SAVE_INTERVAL_SECONDS):
            close_old_connections()
            obj_ref = db_objects.get(target_label)
            if obj_ref is not None:
                verify_data.objects.update_or_create(
                    ObjectRef=obj_ref,
                    CamRef=cam,
                    defaults={"Verified": last_count > 0, "count": int(last_count)},
                )
            last_db_save = time.time()

        if last_count > 0:
            cv2.putText(
                frame,
                f"{target_label} x{last_count}",
                (30, 50),
                cv2.FONT_HERSHEY_SIMPLEX,
                1,
                (0, 255, 0),
                2,
            )
        _draw_boxes(frame, last_boxes)
        cv2.imshow(window_name, frame)

        if cv2.getWindowProperty(window_name, cv2.WND_PROP_VISIBLE) < 1:
            break
        if cv2.waitKey(1) & 0xFF == 27:
            break
        if stop_event.wait(0.01):
            break

    if inference_future is not None:
        inference_future.cancel()
    executor.shutdown(wait=False, cancel_futures=True)
    cap.release()
    cv2.destroyAllWindows()
    with active_camera_runs_lock:
        active_camera_runs.pop(requested_run, None)
