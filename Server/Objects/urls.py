from django.urls import path

from .views import create_objects
urlpatterns = [
    path('create-objects/', create_objects, name='create-objects'),
]