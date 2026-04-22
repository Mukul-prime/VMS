from .models import ObjectDetector
from Camera.models import CreateCamera
import threading

def take_db_data():
    db_data = ObjectDetector.objects.all().values("Name")
    return db_data


def take_db_object_names_threaded():
    """
    Fetch ObjectDetector names from DB using a worker thread.
    Returns a plain list of names.
    """
    result = {"names": []}

    def _worker():
        result["names"] = list(
            ObjectDetector.objects.values_list("Name", flat=True)
        )

    worker = threading.Thread(target=_worker, daemon=True)
    worker.start()
    worker.join()
    return result["names"]



def take_camera_data(cam_id):
    rstp_url = CreateCamera.objects.get(Cam_id=cam_id).rstp_url
    return rstp_url