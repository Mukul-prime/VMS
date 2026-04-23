import cv2
import time

def generate_frames(rtsp_url):
    while True:  # ✅ Outer loop — reconnect karta rehta hai
        cap = cv2.VideoCapture(rtsp_url)
        
        if not cap.isOpened():
            print(f"❌ RTSP connect nahi hua: {rtsp_url}")
            # ✅ Black frame bhejo taaki stream tute nahi
            import numpy as np
            blank = np.zeros((480, 640, 3), dtype=np.uint8)
            _, buffer = cv2.imencode('.jpg', blank)
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + buffer.tobytes() + b'\r\n')
            time.sleep(3)  # 3 sec baad retry
            continue

        while True:
            success, frame = cap.read()
            if not success:
                print(f"⚠️ Frame nahi mila, reconnect kar raha hai...")
                cap.release()
                time.sleep(2)
                break  # ✅ Outer loop mein jaao — reconnect hoga

            _, buffer = cv2.imencode('.jpg', frame)
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + buffer.tobytes() + b'\r\n')