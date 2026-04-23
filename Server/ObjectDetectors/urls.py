from django.urls import path

from .views import *

urlpatterns = [
    path("start_detection/", start_camera, name='start_detection'),
    path("object_total_count/", get_object_total_count, name="object_total_count"),
    path("creaete_objects/",create_objects,name='creaete_objects'),

    path("stop-camera/", stop_camera),
    path("stop-all/", stop_all_cameras),
    path("stop_all_cameras/", stop_all_cameras, name="stop_all_cameras"),
]