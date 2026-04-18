from django.urls import path

from .views import *

urlpatterns = [
    path('create-camera/', add_camera, name='create-objects'),
    path('cameras/', Get_all_cameras, name='cameras'),
    path('streams/<int:cam_id>/', stream_camera, name='stream'),
    path('deleteCam/<int:cam_id>', DeleteCameras, name='deleteCameras'),
    path('getcameraDetails/<int:cam_id>', start_camera, name='start_camera'),
    path('Stop_camera/<int:cam_id>', stop_camera, name='stop_camera'),
    path('stop_all_cameras/', stop_all_cameras, name='stop_all_cameras'),
    path('Computational/<int:cam_id>',Computational,name='Computational'),

]
