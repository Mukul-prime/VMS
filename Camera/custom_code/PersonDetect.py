import cv2
import threading
import time
from ultralytics import YOLO
from deep_sort_realtime.deepsort_tracker import DeepSort

# ===============================
# CONFIG
# ===============================

RTSP_URL = "rtsp://admin:Pratikshat%40123%23@192.168.1.113:554/stream"

YOLO_MODEL = "yolov8m.pt"
CONF_YOLO = 0.4

TERMINAL_LOG_INTERVAL_SEC = 1.0
PERSON_TRACK_MERGE_IOU = 0.42
DRAW_PERSON_MARKERS = True

# ===============================
# HELPERS
# ===============================


def iou_tlbr(a, b):
    ax1, ay1, ax2, ay2 = [float(x) for x in a]
    bx1, by1, bx2, by2 = [float(x) for x in b]
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    iw, ih = max(0.0, ix2 - ix1), max(0.0, iy2 - iy1)
    inter = iw * ih
    if inter <= 0:
        return 0.0
    area_a = max(0.0, ax2 - ax1) * max(0.0, ay2 - ay1)
    area_b = max(0.0, bx2 - bx1) * max(0.0, by2 - by1)
    union = area_a + area_b - inter
    return inter / union if union > 0 else 0.0


def dedupe_person_tracks(tracks, iou_thresh):
    candidates = []
    for track in tracks:
        if not track.is_confirmed():
            continue
        if track.get_det_class() not in (None, "person"):
            continue

        box = track.to_tlbr(orig=True, orig_strict=False)
        if box is None:
            continue
        candidates.append(track)

    def sort_key(track):
        matched_now = 0 if track.time_since_update == 0 else 1
        conf = track.get_det_conf() or 0.0
        return (matched_now, -track.hits, -conf)

    candidates.sort(key=sort_key)

    kept = []
    kept_boxes = []
    for track in candidates:
        box = track.to_tlbr(orig=True, orig_strict=False)
        if box is None:
            continue
        if any(iou_tlbr(box, saved_box) >= iou_thresh for saved_box in kept_boxes):
            continue
        kept_boxes.append(box)
        kept.append((track.track_id, box))

    return kept


def spatial_sort_person_tracks(kept_pairs):
    return sorted(
        kept_pairs,
        key=lambda item: ((item[1][1] + item[1][3]) * 0.5, (item[1][0] + item[1][2]) * 0.5),
    )


def draw_person_markers(frame, markers):
    if not DRAW_PERSON_MARKERS:
        return

    for marker in markers:
        x1, y1, x2, y2 = marker["box"]
        text = f"P{marker['order']}"
        cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 255), 2)
        cv2.putText(
            frame,
            text,
            (x1, max(22, y1 - 8)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.65,
            (0, 255, 255),
            2,
            cv2.LINE_AA,
        )


# ===============================
# GLOBALS
# ===============================

latest_frame = None
tracked_person_ids = []
person_markers = []
lock = threading.Lock()

# ===============================
# MODEL
# ===============================

yolo = YOLO(YOLO_MODEL)

tracker = DeepSort(
    max_age=45,
    n_init=5,
    max_cosine_distance=0.25,
    nms_max_overlap=0.88,
)

# ===============================
# THREAD 1: CAPTURE
# ===============================


def capture():
    global latest_frame

    cap = cv2.VideoCapture(RTSP_URL)
    while True:
        ret, frame = cap.read()
        if not ret:
            time.sleep(0.05)
            continue

        with lock:
            latest_frame = frame.copy()


# ===============================
# THREAD 2: PERSON DETECT + TRACK
# ===============================


def detect_persons():
    global latest_frame, tracked_person_ids, person_markers

    while True:
        with lock:
            frame = None if latest_frame is None else latest_frame.copy()

        if frame is None:
            time.sleep(0.01)
            continue

        results = yolo(frame, conf=CONF_YOLO, classes=[0], verbose=False)[0]
        det_list = []

        for box in results.boxes:
            conf = float(box.conf[0])
            x1, y1, x2, y2 = map(int, box.xyxy[0])
            w, h = x2 - x1, y2 - y1
            det_list.append(([x1, y1, w, h], conf, "person"))

        tracks = tracker.update_tracks(det_list, frame=frame)
        kept = dedupe_person_tracks(tracks, PERSON_TRACK_MERGE_IOU)
        sorted_kept = spatial_sort_person_tracks(kept)

        markers = []
        temp_ids = []
        for index, (track_id, box) in enumerate(sorted_kept, start=1):
            x1, y1, x2, y2 = map(int, box)
            temp_ids.append(track_id)
            markers.append(
                {
                    "track_id": track_id,
                    "order": index,
                    "box": (x1, y1, x2, y2),
                }
            )

        with lock:
            tracked_person_ids = temp_ids
            person_markers = markers


# ===============================
# START THREADS
# ===============================

threading.Thread(target=capture, daemon=True).start()
threading.Thread(target=detect_persons, daemon=True).start()


# ===============================
# DISPLAY LOOP
# ===============================

cv2.namedWindow("Live", cv2.WINDOW_NORMAL)
last_terminal_log = 0.0

while True:
    with lock:
        frame = None if latest_frame is None else latest_frame.copy()
        current_ids = list(tracked_person_ids)
        markers = list(person_markers)

    if frame is None:
        time.sleep(0.01)
        continue

    person_count = len(set(current_ids))

    if TERMINAL_LOG_INTERVAL_SEC > 0:
        now = time.time()
        if now - last_terminal_log >= TERMINAL_LOG_INTERVAL_SEC:
            last_terminal_log = now
            print(f"Persons(tracked)={person_count}", flush=True)

    cv2.putText(
        frame,
        f"Persons (tracked): {person_count}",
        (16, 32),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.85,
        (0, 255, 255),
        2,
        cv2.LINE_AA,
    )

    draw_person_markers(frame, markers)
    cv2.imshow("Live", frame)

    if cv2.waitKey(1) & 0xFF == 27:
        break

cv2.destroyAllWindows()
