from django.urls import path

from . import views
from .views import create_user_data

urlpatterns = [
    path('create-user/', create_user_data, name='create-user'),
]