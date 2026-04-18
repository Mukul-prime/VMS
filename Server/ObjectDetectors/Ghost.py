from rest_framework import serializers

from .models import ObjectDetector


class ObjectDetectors(serializers.ModelSerializer):
    class Meta:
        model = ObjectDetector
        fields = '__all__'


ObjectDetectrsSerializer = ObjectDetectors
