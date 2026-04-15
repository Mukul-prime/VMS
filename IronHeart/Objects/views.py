from . import Phantom
from rest_framework.decorators import api_view
from rest_framework.response import Response
from .models import ObjectsData


# Create your views here.
@api_view(['POST'])
def create_objects(request):
    message =""
    check = None
    if ObjectsData.objects.filter(Name=request.data['Name']).exists():
       return  Response({
           "message" : "Object with this Name already exists",
       "check" : False

       })
    serializer = Phantom.ObjectsSerializer(data=request.data)
    if serializer.is_valid():
        serializer.save()
        return Response({
            "message" : "Object created successfully",
            "check" : True
        })



