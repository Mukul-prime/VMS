import cv2

def generate_frames(rtsp_url):
    cap = cv2.VideoCapture(rtsp_url)

    while True:
        if not cap.isOpened():
            print("Reconnecting camera...")
            cap.release()
            cap = cv2.VideoCapture(rtsp_url)
            continue

        success, frame = cap.read()

        if not success:
            print("Frame failed, retrying...")
            continue   # ❗ break nahi karna

        try:
            _, buffer = cv2.imencode('.jpg', frame)
            frame_bytes = buffer.tobytes()

            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')

        except Exception as e:
            print("Encoding error:", e)
            continue