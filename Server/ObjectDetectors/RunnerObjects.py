import cv2
import os
import time
import re
import json
import math
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
global_tracks_lock = threading.Lock()
global_tracks = {}
global_track_seq = 1
# Shared memory per object label across all cameras.
# Example: shared_object_memory["chair"] => {"count": 2, "last_updated": ...}
shared_object_memory = {}
shared_object_memory_lock = threading.Lock()
active_camera_runs = {}
active_camera_runs_lock = threading.Lock()
GLOBAL_TRACK_MISS_TOLERANCE = int(os.getenv("GLOBAL_TRACK_MISS_TOLERANCE", "3"))

PERFORMANCE_MODE = os.getenv("PERFORMANCE_MODE", "accurate").strip().lower()
LIGHTWEIGHT_MODE = os.getenv("LIGHTWEIGHT_MODE", "1").strip().lower() in {"1", "true", "yes", "on"}

if PERFORMANCE_MODE == "accurate":
    default_candidates = ["yolov8x.pt", "yolov8l.pt", "yolov8m.pt"]
    default_imgsz = 1280
    default_conf = 0.25
    default_interval = 2
    default_workers = 1
else:
    # light mode for fast CPU/GPU usage
    default_candidates = ["yolov8n.pt", "yolov8s.pt", "yolov8m.pt"]
    default_imgsz = 640
    default_conf = 0.45
    default_interval = 4
    default_workers = 1

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
    raise RuntimeError("No YOLO model could be loaded (checked yolov8m.pt/yolov8n.pt).")

model = _loaded_model
BLOCKED_CLASSES = {"person"}
YOLO_TO_DB_ALIASES = {
    "backpack": "bagpack",
}
YOLO_IMGSZ = int(os.getenv("YOLO_IMGSZ", str(default_imgsz)))
YOLO_CONF = float(os.getenv("YOLO_CONF", str(default_conf)))
DETECTION_INTERVAL_SECONDS = int(os.getenv("DETECTION_INTERVAL_SECONDS", str(default_interval)))
INFERENCE_WORKERS = int(os.getenv("INFERENCE_WORKERS", str(default_workers)))
DB_REFRESH_INTERVAL = int(os.getenv("DB_REFRESH_INTERVAL", "5"))
YOLO_IOU = float(os.getenv("YOLO_IOU", "0.55"))
PERSIST_MISS_CYCLES = int(os.getenv("PERSIST_MISS_CYCLES", "3"))
BOX_PERSIST_MISS_CYCLES = int(os.getenv("BOX_PERSIST_MISS_CYCLES", "2"))
YOLO_AUGMENT = os.getenv(
    "YOLO_AUGMENT",
    "1" if PERFORMANCE_MODE == "accurate" else "0"
).strip().lower() in {"1", "true", "yes", "on"}
LAG_INFER_THRESHOLD_SECONDS = float(os.getenv("LAG_INFER_THRESHOLD_SECONDS", "2.2"))
MIN_RUNTIME_IMGSZ = int(os.getenv("MIN_RUNTIME_IMGSZ", "960"))
MAX_DRAW_BOXES = int(os.getenv("MAX_DRAW_BOXES", "40"))
CAPTURE_BUFFER_SIZE = int(os.getenv("CAPTURE_BUFFER_SIZE", "6"))
USE_LOW_LATENCY_FFMPEG = os.getenv("USE_LOW_LATENCY_FFMPEG", "0").strip().lower() in {"1", "true", "yes", "on"}
MAX_CORRUPTED_FRAMES = int(os.getenv("MAX_CORRUPTED_FRAMES", "6"))
REFLECTION_Y_GAP = float(os.getenv("REFLECTION_Y_GAP", "0.03"))
REFLECTION_X_OVERLAP = float(os.getenv("REFLECTION_X_OVERLAP", "0.65"))
REFLECTION_CONF_MARGIN = float(os.getenv("REFLECTION_CONF_MARGIN", "0.08"))
VERIFY_DATA_RETENTION_HOURS = int(os.getenv("VERIFY_DATA_RETENTION_HOURS", "24"))
VERIFY_DATA_CLEANUP_INTERVAL_SECONDS = int(os.getenv("VERIFY_DATA_CLEANUP_INTERVAL_SECONDS", "600"))
GLOBAL_ASSOCIATION_MAX_WORLD_DIST = float(os.getenv("GLOBAL_ASSOCIATION_MAX_WORLD_DIST", "0.08"))
GLOBAL_ASSOCIATION_MAX_AGE_SECONDS = float(os.getenv("GLOBAL_ASSOCIATION_MAX_AGE_SECONDS", "2.5"))
GLOBAL_TRACK_TTL_SECONDS = float(os.getenv("GLOBAL_TRACK_TTL_SECONDS", "10"))

if LIGHTWEIGHT_MODE:
    # Runtime defaults tuned for lower CPU/GPU load.
    YOLO_IMGSZ = min(YOLO_IMGSZ, 640)
    YOLO_CONF = max(YOLO_CONF, 0.35)
    DETECTION_INTERVAL_SECONDS = max(DETECTION_INTERVAL_SECONDS, 3)
    YOLO_AUGMENT = False
    MAX_DRAW_BOXES = min(MAX_DRAW_BOXES, 15)


def _load_camera_homographies():
    """
    Expected JSON in env CAMERA_HOMOGRAPHIES:
    {"1":[[...],[...],[...]],"2":[[...],[...],[...]]}
    Matrices should map normalized image points -> normalized floor/world plane.
    """
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
    """
    OpenCV + FFmpeg tuned open. Helps many HEVC RTSP streams.
    """
    if USE_LOW_LATENCY_FFMPEG:
        os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = (
            "rtsp_transport;tcp|fflags;nobuffer|flags;low_delay|max_delay;500000"
        )
    else:
        # Stable decode mode avoids heavy visual corruption on many RTSP streams.
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
    # Very low dynamic range frames are usually decoder garbage/blank frames.
    if std_val < 4.0:
        return True
    if mean_val <= 2.0 or mean_val >= 253.0:
        return True
    return False


def _run_inference(frame_small, allowed_classes, infer_cfg):
    detections = []
    boxes = []
    h, w = frame_small.shape[:2]
    results = model(
        frame_small,
        conf=infer_cfg["conf"],
        iou=infer_cfg["iou"],
        imgsz=infer_cfg["imgsz"],
        augment=infer_cfg["augment"],
        verbose=False,
    )
    for r in results:
        if r.boxes is None:
            continue
        for box in r.boxes:
            cls_id = int(box.cls[0])
            raw_label = model.names[cls_id].lower()
            label = YOLO_TO_DB_ALIASES.get(raw_label, raw_label)
            label = _canonical_name(label)
            if label in BLOCKED_CLASSES:
                continue
            if label in allowed_classes:
                detections.append(label)
                x1, y1, x2, y2 = box.xyxy[0].tolist()
                boxes.append({
                    "label": label,
                    "x1": max(0.0, min(1.0, x1 / w)),
                    "y1": max(0.0, min(1.0, y1 / h)),
                    "x2": max(0.0, min(1.0, x2 / w)),
                    "y2": max(0.0, min(1.0, y2 / h)),
                    "conf": float(box.conf[0]),
                })
    filtered_boxes = boxes if LIGHTWEIGHT_MODE else _filter_reflection_boxes(boxes)
    filtered_detections = [item["label"] for item in filtered_boxes]
    return filtered_detections, filtered_boxes


def _draw_boxes(frame, boxes, max_boxes=40):
    if not boxes:
        return
    frame_h, frame_w = frame.shape[:2]
    for item in boxes[:max(1, max_boxes)]:
        x1 = int(item["x1"] * frame_w)
        y1 = int(item["y1"] * frame_h)
        x2 = int(item["x2"] * frame_w)
        y2 = int(item["y2"] * frame_h)
        label = item.get("label", "object")

        cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
        cv2.putText(
            frame,
            label,
            (x1, max(20, y1 - 8)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.6,
            (0, 255, 0),
            2,
        )


def _x_overlap_ratio(box_a, box_b):
    left = max(box_a["x1"], box_b["x1"])
    right = min(box_a["x2"], box_b["x2"])
    inter_w = max(0.0, right - left)
    base_w = max(1e-6, min(box_a["x2"] - box_a["x1"], box_b["x2"] - box_b["x1"]))
    return inter_w / base_w


def _filter_reflection_boxes(boxes):
    """
    Remove lower-confidence mirrored boxes likely coming from floor/glass reflection.
    """
    if not boxes:
        return []

    kept = []
    for box in sorted(boxes, key=lambda b: b.get("conf", 0.0), reverse=True):
        is_reflection = False
        for anchor in kept:
            if box["label"] != anchor["label"]:
                continue
            if box["y1"] <= anchor["y1"]:
                continue
            x_overlap = _x_overlap_ratio(box, anchor)
            y_gap = box["y1"] - anchor["y2"]
            if (
                x_overlap >= REFLECTION_X_OVERLAP
                and y_gap >= -0.02
                and y_gap <= REFLECTION_Y_GAP
                and box.get("conf", 0.0) + REFLECTION_CONF_MARGIN < anchor.get("conf", 0.0)
            ):
                is_reflection = True
                break
        if not is_reflection:
            kept.append(box)
    return kept


def _apply_count_persistence(smoothed_counts, persisted_counts, missing_streaks, hold_cycles):
    """
    Keep last seen counts alive for a few cycles so labels do not flicker.
    """
    stable_counts = Counter()
    current_labels = set(smoothed_counts.keys())
    remembered_labels = set(persisted_counts.keys())

    for label in current_labels | remembered_labels:
        new_count = smoothed_counts.get(label, 0)
        old_count = persisted_counts.get(label, 0)

        if new_count > 0:
            stable_counts[label] = new_count
            missing_streaks[label] = 0
            continue

        miss_count = missing_streaks.get(label, 0) + 1
        missing_streaks[label] = miss_count
        if old_count > 0 and miss_count <= max(1, hold_cycles):
            stable_counts[label] = old_count

    for label in list(missing_streaks.keys()):
        if label not in stable_counts and missing_streaks[label] > max(1, hold_cycles):
            del missing_streaks[label]

    return stable_counts


def _merge_boxes_with_persistence(new_boxes, persisted_boxes, box_missing_streaks, hold_cycles):
    """
    Keep last known box of a label for a few cycles when detector misses it.
    """
    latest_by_label = {}
    for box in new_boxes:
        latest_by_label[box["label"]] = box

    merged = []
    active_labels = set(latest_by_label.keys()) | set(persisted_boxes.keys())
    for label in active_labels:
        if label in latest_by_label:
            persisted_boxes[label] = latest_by_label[label]
            box_missing_streaks[label] = 0
            merged.append(latest_by_label[label])
            continue

        miss_count = box_missing_streaks.get(label, 0) + 1
        box_missing_streaks[label] = miss_count
        if miss_count <= max(1, hold_cycles) and label in persisted_boxes:
            merged.append(persisted_boxes[label])
        else:
            persisted_boxes.pop(label, None)

    for label in list(box_missing_streaks.keys()):
        if label not in persisted_boxes:
            del box_missing_streaks[label]

    return merged


def _project_box_to_world(cam_id, box):
    h = CAMERA_HOMOGRAPHIES.get(int(cam_id))
    if h is None:
        return None
    # Use bottom-center point of box as floor-contact approximation.
    px = (box["x1"] + box["x2"]) / 2.0
    py = box["y2"]
    point = np.array([[[px, py]]], dtype=np.float32)
    mapped = cv2.perspectiveTransform(point, h)[0][0]
    return float(mapped[0]), float(mapped[1])


def _update_global_unique_count(cam_id, label, boxes):
    """
    Cross-camera association using world-map node tracking:
    - same location -> same node -> visited=True (count unchanged)
    - different location -> create node -> count +1
    - temporarily missed nodes are tolerated for a few cycles
    """
    global global_track_seq
    now = time.time()
    world_points = []
    for box in boxes:
        if box.get("label") != label:
            continue
        point = _project_box_to_world(cam_id, box)
        if point is not None:
            world_points.append(point)

    # No calibration for this camera -> cannot safely deduplicate across cameras.
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
        # Cleanup stale tracks first.
        for track_id in list(global_tracks.keys()):
            if now - global_tracks[track_id]["last_seen"] > max(1.0, GLOBAL_TRACK_TTL_SECONDS):
                del global_tracks[track_id]

        # Mark label nodes as not visited for this update cycle.
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
                global_tracks[best_id]["world_point"] = (
                    0.7 * prev_x + 0.3 * wx,
                    0.7 * prev_y + 0.3 * wy,
                )
                global_tracks[best_id]["last_seen"] = now
                global_tracks[best_id]["cameras"].add(int(cam_id))
                global_tracks[best_id]["visited"] = True
                global_tracks[best_id]["miss_cycles"] = 0

        # Keep count stable during short misses due to motion/occlusion.
        for track in global_tracks.values():
            if track["label"] != label:
                continue
            if track.get("visited"):
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
            if (
                age <= max(0.3, GLOBAL_ASSOCIATION_MAX_AGE_SECONDS)
                and track.get("miss_cycles", 0) <= max(1, GLOBAL_TRACK_MISS_TOLERANCE)
            ):
                active += 1

        # Update shared per-object memory for all cameras.
        with shared_object_memory_lock:
            shared_object_memory[label] = {
                "count": int(active),
                "last_updated": now,
                "last_camera_id": int(cam_id),
            }
        return active


def _get_shared_object_count(label):
    with shared_object_memory_lock:
        payload = shared_object_memory.get(label)
        if not payload:
            return 0
        return int(payload.get("count", 0))


def run_camera_detection(cam_id, stop_event, target_object_name=None):
    requested_label = _canonical_name(target_object_name) if target_object_name else ""
    requested_run = (int(cam_id), requested_label)
    with active_camera_runs_lock:
        # Prevent duplicate worker for the same camera+object pair,
        # but allow multiple cameras to run in parallel.
        if requested_run in active_camera_runs:
            print(f"[REJECTED] Camera/object run already active: {requested_run}")
            return
        active_camera_runs[requested_run] = True

    print(f"[START] Camera {cam_id}")
    print(
        "[MODE]",
        {
            "performance": PERFORMANCE_MODE,
            "lightweight": LIGHTWEIGHT_MODE,
            "imgsz": YOLO_IMGSZ,
            "conf": YOLO_CONF,
            "iou": YOLO_IOU,
            "augment": YOLO_AUGMENT,
            "interval_s": DETECTION_INTERVAL_SECONDS,
            "workers": INFERENCE_WORKERS,
        },
    )

    cam = CreateCamera.objects.filter(Cam_id=cam_id).first()
    if not cam:
        print(f"[ERROR] Camera {cam_id} not found in DB")
        with active_camera_runs_lock:
            active_camera_runs.pop(requested_run, None)
        return

    rtsp_url = cam.rstp_url

    cap = _open_camera_stream(rtsp_url)

    if not cap.isOpened():
        print(f"[ERROR] Camera {cam_id} not opened")
        with active_camera_runs_lock:
            active_camera_runs.pop(requested_run, None)
        return

    # 🔥 Load DB objects (runtime refresh)
    db_objects = _load_db_objects()
    db_names_set = set(db_objects.keys())
    target_label = _canonical_name(target_object_name) if target_object_name else ""
    if not target_label:
        print("[ERROR] target_object_name is required")
        cap.release()
        cv2.destroyAllWindows()
        with active_camera_runs_lock:
            active_camera_runs.pop(requested_run, None)
        return
    if target_label not in db_names_set:
        print(f"[ERROR] Requested object '{target_object_name}' not found in DB")
        cap.release()
        cv2.destroyAllWindows()
        with active_camera_runs_lock:
            active_camera_runs.pop(requested_run, None)
        return
    db_names_set = {target_label}
    print(f"[TARGET OBJECT] {target_label}")
    last_db_refresh = time.time()

    print("[DB OBJECTS]:", db_names_set)

    last_db_update = time.time()
    last_cleanup_at = 0
    next_detection_at = time.time()
    runtime_imgsz = YOLO_IMGSZ
    runtime_interval = max(1, DETECTION_INTERVAL_SECONDS)
    runtime_augment = YOLO_AUGMENT

    # Single-object runtime cache
    last_detected_boxes = []
    last_counts = Counter()
    persisted_counts = Counter()
    count_missing_streaks = Counter()
    persisted_boxes = {}
    box_missing_streaks = Counter()
    inference_future = None
    inference_started_at = None
    executor = ThreadPoolExecutor(max_workers=max(1, INFERENCE_WORKERS))
    corrupted_frames = 0

    # 🔥 GUI Window (Resizable with close/minimize)
    window_name = f"Camera {cam_id}"
    cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(window_name, 1280, 720)

    while not stop_event.is_set():
        ret, frame = cap.read()

        if not ret or frame is None:
            print(f"[ERROR] Camera {cam_id} frame failed → reconnecting...")
            cap.release()
            if stop_event.wait(1):
                break
            cap = _open_camera_stream(rtsp_url)
            continue
        if _is_corrupted_frame(frame):
            corrupted_frames += 1
            if corrupted_frames >= max(1, MAX_CORRUPTED_FRAMES):
                print(f"[ERROR] Camera {cam_id} corrupted frames detected → reconnecting...")
                cap.release()
                if stop_event.wait(1):
                    break
                cap = _open_camera_stream(rtsp_url)
                corrupted_frames = 0
            continue
        corrupted_frames = 0

        # Keep allowed object names fresh while app is running.
        if time.time() - last_db_refresh >= DB_REFRESH_INTERVAL:
            refreshed_objects = _load_db_objects()
            if refreshed_objects:
                db_objects = refreshed_objects
                refreshed_names = set(db_objects.keys())
                if target_label:
                    if target_label in refreshed_names:
                        db_names_set = {target_label}
                    else:
                        print(f"[STOP] Target object '{target_label}' removed from DB")
                        break
                print(f"[DB REFRESH] {db_names_set}")
            last_db_refresh = time.time()

        # Periodic cleanup: remove stale verify_data records older than retention window.
        if time.time() - last_cleanup_at >= max(60, VERIFY_DATA_CLEANUP_INTERVAL_SECONDS):
            cutoff = timezone.now() - timedelta(hours=max(1, VERIFY_DATA_RETENTION_HOURS))
            deleted_count, _ = verify_data.objects.filter(updated_at__lt=cutoff).delete()
            if deleted_count:
                print(f"[CLEANUP] Deleted {deleted_count} stale verify_data rows older than {cutoff}")
            last_cleanup_at = time.time()

        # Pick up async inference results when ready.
        if inference_future is not None and inference_future.done():
            try:
                detected_names, detected_boxes = inference_future.result()
            except Exception as infer_error:
                print(f"[INFERENCE ERROR] {infer_error}")
                detected_names = []
                detected_boxes = []
            inference_elapsed = 0.0
            if inference_started_at is not None:
                inference_elapsed = time.time() - inference_started_at
            if inference_elapsed > LAG_INFER_THRESHOLD_SECONDS:
                runtime_augment = False
                runtime_imgsz = max(MIN_RUNTIME_IMGSZ, runtime_imgsz - 160)
                runtime_interval = min(6, runtime_interval + 1)
                print(
                    f"[LAG GUARD] infer={inference_elapsed:.2f}s -> "
                    f"imgsz={runtime_imgsz}, augment={runtime_augment}, interval={runtime_interval}s"
                )
            inference_future = None
            inference_started_at = None
            last_detected_boxes = _merge_boxes_with_persistence(
                detected_boxes,
                persisted_boxes,
                box_missing_streaks,
                BOX_PERSIST_MISS_CYCLES,
            )
            raw_counts = Counter()
            if target_label:
                _update_global_unique_count(cam_id, target_label, detected_boxes)
                shared_count = _get_shared_object_count(target_label)
                raw_counts[target_label] = shared_count
                print(f"[GLOBAL SHARED COUNT] {target_label}: {shared_count}")
            last_counts = _apply_count_persistence(
                raw_counts,
                persisted_counts,
                count_missing_streaks,
                PERSIST_MISS_CYCLES,
            )
            persisted_counts = Counter(last_counts)

            if target_label:
                if raw_counts.get(target_label, 0) > 0:
                    print(f"[DETECTED] ['{target_label}']")
                print(f"[COUNTS RAW] {dict(raw_counts)}")
                print(f"[COUNTS STABLE] {dict(last_counts)}")

        # Submit inference every N seconds.
        if inference_future is None and time.time() >= next_detection_at:
            frame_small = frame
            infer_cfg = {
                "conf": YOLO_CONF,
                "iou": YOLO_IOU,
                "imgsz": runtime_imgsz,
                "augment": runtime_augment,
            }
            inference_started_at = time.time()
            inference_future = executor.submit(_run_inference, frame_small, db_names_set, infer_cfg)
            next_detection_at = time.time() + runtime_interval

        # 🔥 DB SAVE (SAFE + OPTIMIZED)
        if time.time() - last_db_update > max(1, DETECTION_INTERVAL_SECONDS):

            close_old_connections()

            counts = Counter(last_counts)
            labels_to_persist = [target_label] if target_label else []
            print(f"[MATCHED] {labels_to_persist}")
            print(f"[COUNTS] {dict(counts)}")

            for obj_name in labels_to_persist:
                try:
                    obj_ref = db_objects.get(obj_name)
                    if obj_ref is None:
                        continue
                    current_count = int(counts.get(obj_name, 0))
                    is_verified = current_count > 0
                    obj, created = verify_data.objects.update_or_create(
                        ObjectRef=obj_ref,
                        CamRef=cam,
                        defaults={
                            "Verified": is_verified,
                            "count": current_count
                        }
                    )

                    print(
                        f"[SAVED] {obj_name} → {current_count} | Verified={is_verified} | Created={created}"
                    )

                except Exception as e:
                    print(f"[DB ERROR] {e}")

            last_db_update = time.time()

        # 🔥 Overlay text (stable)
        detected_count = int(last_counts.get(target_label, 0)) if target_label else 0
        if detected_count > 0 and target_label:
            text = f"{target_label} x{detected_count}"
            cv2.putText(frame, text, (30, 50),
                        cv2.FONT_HERSHEY_SIMPLEX, 1,
                        (0, 255, 0), 2)
        _draw_boxes(frame, last_detected_boxes, MAX_DRAW_BOXES)

        # 🔥 Display
        cv2.imshow(window_name, frame)

        # Window close detect
        if cv2.getWindowProperty(window_name, cv2.WND_PROP_VISIBLE) < 1:
            print("Window closed")
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

    print(f"[STOP] Camera {cam_id}")