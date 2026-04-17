import cv2
import threading
from ultralytics import YOLO
from deep_sort_realtime.deepsort_tracker import DeepSort
from .models import Persons, CreateCamera
import time
from django.utils.timezone import now
from django.db import close_old_connections
import traceback

camera_flags = {}

def runner(rtsp_url, cam_id):

    CONF_YOLO = 0.25   # 🔥 improved detection

    latest_frame = None
    lock = threading.Lock()
    person_ids = []

    camera_flags[cam_id] = True

    yolo = YOLO("yolov8m.pt")
    tracker = DeepSort(max_age=40)

    # ===============================
    # THREAD 1: CAPTURE
    # ===============================
    def capture():
        nonlocal latest_frame
        cap = cv2.VideoCapture(rtsp_url)

        while camera_flags.get(cam_id, False):
            ret, frame = cap.read()
            if not ret:
                continue

            with lock:
                latest_frame = frame.copy()

        cap.release()

    # ===============================
    # THREAD 2: DETECT + DB UPDATE
    # ===============================
    def detect():
        nonlocal latest_frame, person_ids

        last_save = 0
        smoothed_count = 0

        while camera_flags.get(cam_id, False):
            try:
                if latest_frame is None:
                    continue

                with lock:
                    frame = latest_frame.copy()

                results = yolo(frame, verbose=False)[0]

                detections = []

                for box in results.boxes:
                    conf = float(box.conf[0])
                    cls = int(box.cls[0])
                    label = yolo.names[cls]

                    if label != "person" or conf < CONF_YOLO:
                        continue

                    x1, y1, x2, y2 = map(int, box.xyxy[0])
                    w, h = x2 - x1, y2 - y1

                    detections.append(([x1, y1, w, h], conf, "person"))

                print("YOLO detections:", len(detections))  # 🔍 DEBUG

                tracks = tracker.update_tracks(detections, frame=frame)

                temp_ids = []

                for t in tracks:
                    # 🔥 FIX: no strict confirmation
                    if t.time_since_update > 2:
                        continue
                    temp_ids.append(t.track_id)

                with lock:
                    person_ids = temp_ids

                # 🔥 HYBRID COUNT (BEST)
                current_count = max(len(detections), len(set(person_ids)))

                # smoothing
                alpha = 0.4
                smoothed_count = int(
                    alpha * current_count + (1 - alpha) * smoothed_count
                )

                print(f"👤 Cam {cam_id} Count: {smoothed_count}")

                # ===============================
                # 🔥 DB SAVE
                # ===============================
                if time.time() - last_save > 2:
                    last_save = time.time()

                    today = now().date()

                    close_old_connections()

                    try:
                        cam = CreateCamera.objects.get(Cam_id=cam_id)
                        print("✅ Camera Found:", cam)
                    except CreateCamera.DoesNotExist:
                        print("❌ Camera not found:", cam_id)
                        continue

                    Persons.objects.update_or_create(
                        Cam_ids=cam,
                        date=today,
                        defaults={"count": smoothed_count}
                    )

                    print(f"💾 Saved → Cam {cam_id} | {today} | {smoothed_count}")

            except Exception as e:
                print("❌ ERROR:", e)
                traceback.print_exc()

    # ===============================
    # THREAD 3: DISPLAY
    # ===============================
    def display():
        nonlocal latest_frame, person_ids

        window_name = f"Camera {cam_id}"
        cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)

        while camera_flags.get(cam_id, False):
            if latest_frame is None:
                continue

            with lock:
                frame = latest_frame.copy()
                ids = list(set(person_ids))

            cv2.putText(frame, f"Persons: {len(ids)}",
                        (20, 40),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        1,
                        (0, 255, 255),
                        2)

            cv2.imshow(window_name, frame)

            if cv2.waitKey(1) & 0xFF == 27:
                break

        cv2.destroyWindow(window_name)

    # ===============================
    # START THREADS
    # ===============================
    print(f"🚀 Camera {cam_id} Started")

    threading.Thread(target=capture, daemon=True).start()
    threading.Thread(target=detect, daemon=True).start()
    threading.Thread(target=display, daemon=True).start()