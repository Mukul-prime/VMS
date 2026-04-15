from rest_framework import serializers

from .models import CreateCamera


class CreatecameraS(serializers.ModelSerializer):
    class Meta:
        model = CreateCamera
        fields = '__all__'


CameraSerializer = CreatecameraS
