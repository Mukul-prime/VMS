from rest_framework import serializers

from .models import ObjectsData


class ObjectsSerializer(serializers.ModelSerializer):
    class Meta:
        model = ObjectsData
        fields = '__all__'
