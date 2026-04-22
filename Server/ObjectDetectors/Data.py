from .DB_data_Taker import take_db_data, take_db_object_names_threaded
from ultralytics import YOLO
from deep_sort_realtime.deepsort_tracker import DeepSort
import cv2
import threading
import time
from Camera.models import CreateCamera
from .models import ObjectDetector, verify_data as VerifyDataModel

def getData():
    db_data = [{"Name": name} for name in take_db_object_names_threaded() if name]
    return db_data


def yolo_model_load():
    model = YOLO("yolov8m.pt")
    return model


def verify_data(cam_id, detected_objects):
    """
    Compare YOLO detected objects with DB objects.
    If a detected object exists in DB, mark/create verify_data as Verified=True.
    """
    if detected_objects is None:
        detected_objects = []

    db_names = {
        str(name).strip().lower()
        for name in take_db_object_names_threaded()
        if name
    }

    normalized_detected = []
    for item in detected_objects:
        # Supports list like ["person", "car"] or [{"name": "person"}]
        if isinstance(item, dict):
            name = (item.get("name") or item.get("Name") or item.get("class") or "").strip()
        else:
            name = str(item).strip()
        if name:
            normalized_detected.append(name.lower())

    detected_set = set(normalized_detected)
    # Strict filter: process only names that exist in ObjectDetector table.
    matched_names = sorted(detected_set.intersection(db_names))
    ignored_names = sorted(detected_set.difference(db_names))

    camera = CreateCamera.objects.get(Cam_id=cam_id)

    for name in matched_names:
        obj = ObjectDetector.objects.get(Name__iexact=name)
        row, created = VerifyDataModel.objects.get_or_create(
            ObjectRef=obj,
            CamRef=camera,
            defaults={"Verified": True, "count": 1},
        )
        if not created:
            row.Verified = True
            row.count = (row.count or 0) + 1
            row.save(update_fields=["Verified", "count"])

    return {
        "cam_id": cam_id,
        "matched": bool(matched_names),
        "processed_objects": matched_names,
        "ignored_objects": ignored_names,
    }


    

