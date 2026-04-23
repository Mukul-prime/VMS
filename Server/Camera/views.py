from rest_framework import status
from django.http import StreamingHttpResponse, JsonResponse
from . import Mark91
from .Frames import generate_frames
from .RunnerData import runner, camera_flags
from rest_framework.decorators import api_view
from rest_framework.response import Response
import threading
from .models import CreateCamera


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


@api_view(['GET'])
def Get_all_cameras(request):
    cams = CreateCamera.objects.all()
    serializer = Mark91.CreatecameraS(cams, many=True)
    return Response(serializer.data)


# ✅ @api_view NAHI lagana — StreamingHttpResponse ke saath kaam nahi karta
def stream_camera(request, cam_id):
    try:
        cam = CreateCamera.objects.get(Cam_id=cam_id)
    except CreateCamera.DoesNotExist:
        return JsonResponse({"error": "Camera not found"}, status=404)

    response = StreamingHttpResponse(
        generate_frames(cam.rstp_url),
        content_type='multipart/x-mixed-replace; boundary=frame'
    )

    # ✅ Streaming ke liye zaroori headers
    response["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response["Pragma"] = "no-cache"
    response["X-Accel-Buffering"] = "no"
    response["Access-Control-Allow-Origin"] = "*"

    return response


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

    camera_flags[cam_id] = False
    return Response({"message": "Camera stopped"})


@api_view(['GET'])
def stop_all_cameras(request):
    if not camera_flags:
        return Response({"message": "No cameras running"})

    for cam_id in list(camera_flags.keys()):
        camera_flags[cam_id] = False

    camera_flags.clear()
    return Response({"message": "All cameras stopped and cleared"})