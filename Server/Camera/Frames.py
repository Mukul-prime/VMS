import cv2
import os
import time

STREAM_TARGET_FPS = int(os.getenv("STREAM_TARGET_FPS", "12"))
STREAM_JPEG_QUALITY = int(os.getenv("STREAM_JPEG_QUALITY", "70"))
STREAM_WIDTH = int(os.getenv("STREAM_WIDTH", "960"))


def _open_rtsp_capture(rtsp_url):
    # HEVC RTSP streams are usually more stable on TCP + low buffer.
    os.environ.setdefault(
        "OPENCV_FFMPEG_CAPTURE_OPTIONS",
        "rtsp_transport;tcp|fflags;nobuffer|flags;low_delay|max_delay;500000",
    )
    cap = cv2.VideoCapture(rtsp_url, cv2.CAP_FFMPEG)
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 2)
    return cap


def generate_frames(rtsp_url):
    cap = _open_rtsp_capture(rtsp_url)
    last_ok_frame_time = time.time()
    reconnect_after_sec = 3.0
    frame_interval = 1.0 / max(1, STREAM_TARGET_FPS)
    next_emit_at = time.time()

    while True:
        if not cap.isOpened():
            print("Reconnecting camera...")
            cap.release()
            time.sleep(0.5)
            cap = _open_rtsp_capture(rtsp_url)
            continue

        success, frame = cap.read()

        if not success or frame is None:
            # Most HEVC POC decode warnings are transient; retry quickly.
            if time.time() - last_ok_frame_time > reconnect_after_sec:
                print("Frame decode unstable, reconnecting stream...")
                cap.release()
                time.sleep(0.4)
                cap = _open_rtsp_capture(rtsp_url)
            else:
                time.sleep(0.01)
            continue

        last_ok_frame_time = time.time()
        now = time.time()
        if now < next_emit_at:
            # Drop extra frames to keep stream near-real-time.
            continue
        next_emit_at = now + frame_interval

        if STREAM_WIDTH > 0:
            h, w = frame.shape[:2]
            if w > STREAM_WIDTH:
                scale = STREAM_WIDTH / float(w)
                frame = cv2.resize(
                    frame,
                    (int(w * scale), int(h * scale)),
                    interpolation=cv2.INTER_AREA,
                )

        try:
            ok, buffer = cv2.imencode(
                ".jpg",
                frame,
                [int(cv2.IMWRITE_JPEG_QUALITY), max(30, min(95, STREAM_JPEG_QUALITY))],
            )
            if not ok:
                continue
            frame_bytes = buffer.tobytes()

            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')

        except Exception as e:
            print("Encoding error:", e)
            continue