from .models import ObjectDetector
from Camera.models import CreateCamera

def take_db_data():
    db_data = ObjectDetector.objects.all().values("Name")
    return db_data



def take_camera_data(cam_id):
    rstp_url = CreateCamera.objects.get(Cam_id=cam_id).rstp_url
    return rstp_url