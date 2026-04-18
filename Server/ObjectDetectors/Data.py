from .DB_data_Taker import take_db_data
from ultralytics import YOLO
from deep_sort_realtime.deepsort_tracker import DeepSort
import cv2
import threading
import time
from Camera.models import CreateCamera

def getData():
    db_data = list(take_db_data().values("Name"))
    return db_data


def yolo_model_load():
    model = YOLO("yolov8m.pt")
    return model



    

