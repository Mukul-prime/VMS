from rest_framework import status
from django.http import StreamingHttpResponse
from . import Mark91
from .Frames import generate_frames
from .RunnerData import runner, camera_flags
from rest_framework.decorators import api_view
from rest_framework.decorators import api_view
from rest_framework.response import Response
import threading
from .models import CreateCamera

# Create your views here.
@api_view(['POST'])
def add_camera(request):
    rstp_url = request.data.get("rstp_url")
    if CreateCamera.objects.filter(rstp_url=rstp_url).exists():
        return Response({"message": "Camera already exists"}, status=status.HTTP_400_BAD_REQUEST)

    ip_address = request.data.get("ip_address")
    if CreateCamera.objects.filter(ip_address=ip_address).exists():
        return Response({"message": "Camera already exists"}, status=status.HTTP_400_BAD_REQUEST)

    serializer = Mark91.CreatecameraS(data=request.data)
    if serializer.is_valid():
        serializer.save()
        return Response({
            "message": "Camera created successfully",
            "check": True
        }, status=status.HTTP_201_CREATED)

    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


#  get a Camera access by All
@api_view(['GET'])
def Get_all_cameras(request):
    cams = CreateCamera.objects.all()
    serializer = Mark91.CreatecameraS(cams, many=True)
    return Response(serializer.data)


@api_view(['GET'])
def stream_camera(request, cam_id):
    cam = CreateCamera.objects.get(Cam_id=cam_id)

    return StreamingHttpResponse(
        generate_frames(cam.rstp_url),
        content_type='multipart/x-mixed-replace; boundary=frame'
    )


@api_view(['DELETE'])
def DeleteCameras(request, cam_id):
    if CreateCamera.objects.filter(Cam_id=cam_id).exists():
        cams = CreateCamera.objects.get(Cam_id=cam_id)
        cams.delete()
        return Response({"message": "Camera deleted"})
    return Response({"message": "Camera Not exists"}, status=status.HTTP_400_BAD_REQUEST)


running_cameras = {}






@api_view(['GET'])
def start_camera(request, cam_id):
    try:
        cam = CreateCamera.objects.get(Cam_id=cam_id)

        if cam_id in running_cameras:
            return Response({"message": "Already running"})

        t = threading.Thread(
            target=runner,
            args=(cam.rstp_url, cam_id),
            daemon=True
        )
        t.start()

        running_cameras[cam_id] = t

        return Response({"message": "Camera started"})

    except CreateCamera.DoesNotExist:
        return Response({"message": "Camera not found"})



@api_view(['GET'])
def stop_camera(request, cam_id):
    if cam_id not in camera_flags:
        return Response({"message": "Camera not running"})

    camera_flags[cam_id] = False  #  STOP SIGNAL

    return Response({"message": "Camera stopped"})


@api_view(['GET'])
def stop_all_cameras(request):

    if not camera_flags:
        return Response({"message": "No cameras running"})

    for cam_id in list(camera_flags.keys()):
        camera_flags[cam_id] = False

    camera_flags.clear()   # 🔥 clean memory

    return Response({"message": "All cameras stopped and cleared"})