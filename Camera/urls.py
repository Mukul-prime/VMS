from django.urls import path

from .views import *
urlpatterns = [
    path('create-camera/', add_camera, name='create-objects'),
    path('cameras/',Get_all_cameras, name='cameras'),
    path('streams/<int:cam_id>',stream_camera, name='stream'),
     path('deleteCam/<int:cam_id>' ,DeleteCameras, name='deleteCameras'),


]