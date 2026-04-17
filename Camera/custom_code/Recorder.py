import cv2
import os
from datetime import datetime

# ===============================
# CONFIG
# ===============================

rtsp_url = "rtsp://admin:Pratikshat%40123%23@192.168.1.112:554/stream1"

save_folder = "recordings"
os.makedirs(save_folder, exist_ok=True)

# File name with timestamp
filename = datetime.now().strftime("%Y%m%d_%H%M%S") + ".avi"
file_path = os.path.join(save_folder, filename)

# ===============================
# CONNECT RTSP
# ===============================

cap = cv2.VideoCapture(rtsp_url)

if not cap.isOpened():
    print("❌ Cannot open RTSP stream")
    exit()

# Get stream properties
frame_width = int(cap.get(3))
frame_height = int(cap.get(4))
fps = int(cap.get(cv2.CAP_PROP_FPS))

if fps == 0:
    fps = 20  # fallback

# ===============================
# VIDEO WRITER
# ===============================

fourcc = cv2.VideoWriter_fourcc(*'XVID')
out = cv2.VideoWriter(file_path, fourcc, fps, (frame_width, frame_height))

print(f"✅ Recording started: {file_path}")

# ===============================
# LOOP
# ===============================

while True:
    ret, frame = cap.read()

    if not ret:
        print("⚠️ Frame not received")
        break

    out.write(frame)

    # Optional preview
    cv2.imshow("RTSP", frame)

    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

# ===============================
# CLEANUP
# ===============================

cap.release()
out.release()
cv2.destroyAllWindows()

print("✅ Recording saved")