import cv2
import threading
from ultralytics import YOLO
from deep_sort_realtime.deepsort_tracker import DeepSort

RTSP_URL = "rtsp://admin:Pratikshat%40123%23@192.168.1.113:554/stream"
CONF_YOLO = 0.4



latest_frame = None
lock = threading.Lock()
person_ids = []
person_boxes = []


yolo = YOLO("yolov8n.pt")
tracker = DeepSort(max_age=40)



def capture():
    global latest_frame
    cap = cv2.VideoCapture(RTSP_URL)

    while True:
        ret, frame = cap.read()
        if not ret:
            continue

        with lock:
            latest_frame = frame.copy()



def detect():
    global latest_frame, person_ids, person_boxes

    while True:
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

        tracks = tracker.update_tracks(detections, frame=frame)

        temp_ids = []
        temp_boxes = []

        for t in tracks:
            if not t.is_confirmed():
                continue

            track_id = t.track_id
            l, t_, r, b = map(int, t.to_ltrb())

            temp_ids.append(track_id)
            temp_boxes.append((track_id, l, t_, r, b))

        with lock:
            person_ids = temp_ids
            person_boxes = temp_boxes



threading.Thread(target=capture, daemon=True).start()
threading.Thread(target=detect, daemon=True).start()



cv2.namedWindow("Person Tracking", cv2.WINDOW_NORMAL)

while True:
    if latest_frame is None:
        continue

    with lock:
        frame = latest_frame.copy()
        ids = list(set(person_ids))
        boxes = list(person_boxes)


    count = len(ids)


    for tid, x1, y1, x2, y2 in boxes:
        cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 255), 2)
        cv2.putText(frame, f"P{tid}", (x1, y1 - 10),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2)

   
    cv2.putText(frame, f"Persons: {count}", (20, 40),
                cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 255), 2)

    cv2.imshow("Person Tracking", frame)

    if cv2.waitKey(1) & 0xFF == 27:
        break

cv2.destroyAllWindows()