import face_recognition
import numpy as np
import base64

def image_to_encoding_string(image_path):
    # Load image
    image = face_recognition.load_image_file(image_path)

    # Get face encodings
    encodings = face_recognition.face_encodings(image)

    if not encodings:
        return None  # No face found

    encoding = encodings[0]  # Take first face

    # Convert numpy array → bytes
    encoding_bytes = encoding.tobytes()

    # Convert bytes → base64 string
    encoding_string = base64.b64encode(encoding_bytes).decode('utf-8')

    return encoding_string