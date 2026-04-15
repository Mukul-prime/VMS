from rest_framework import serializers
from .models import UserD

class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = UserD
        fields = '__all__'