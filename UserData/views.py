from .models import UserD
from .serializers import UserSerializer
from rest_framework.decorators import api_view, parser_classes
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework.response import Response
from .GetFaceStringData import image_to_encoding_string
@api_view(['POST'])
@parser_classes([MultiPartParser, FormParser])
def create_user_data(request):
    face_data = None
    email = request.data.get("Email")

    if UserD.objects.filter(Email=email).exists():
        return Response({
            "message": "User already exists",
            "check": False
        })

    image_file = request.FILES.get("Image")

    if image_file:
        image_file.seek(0)
        face_data = image_to_encoding_string(image_file)
        image_file.seek(0)

    data = request.data.copy()
    data['FaceEncoding'] = face_data

    serializer = UserSerializer(data=data)

    if serializer.is_valid():
        serializer.save()
        return Response({
            "message": "User created successfully",
            "check": True
        })
    return Response(serializer.errors)