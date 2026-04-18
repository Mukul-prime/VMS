import threading

from django.db.models import Model
from django.http import StreamingHttpResponse, JsonResponse
from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.response import Response

from . import Mark91
from .Frames import generate_frames
from .RunnerData import camera_flags, runner
from .models import CreateCamera
from .models import Persons


running_cameras = {}


@api_view(["POST"])
def add_camera(request):
    rstp_url = request.data.get("rstp_url")
    if rstp_url and CreateCamera.objects.filter(rstp_url=rstp_url).exists():
        return Response(
            {"message": "Camera already exists"},
            status=status.HTTP_400_BAD_REQUEST,
        )

    ip_address = request.data.get("ip_address")
    if ip_address and CreateCamera.objects.filter(ip_address=ip_address).exists():
        return Response(
            {"message": "Camera already exists"},
            status=status.HTTP_400_BAD_REQUEST,
        )

    serializer = Mark91.CreatecameraS(data=request.data)
    if serializer.is_valid():
        serializer.save()
        return Response(
            {
                "message": "Camera created successfully",
                "check": True,
            },
            status=status.HTTP_201_CREATED,
        )

    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(["GET"])
def Get_all_cameras(request):
    cams = CreateCamera.objects.all()
    serializer = Mark91.CreatecameraS(cams, many=True)
    return Response(serializer.data)


@api_view(["GET"])
def stream_camera(request, cam_id):
    cam = CreateCamera.objects.filter(Cam_id=cam_id).first()

    if cam is None:
        return Response(
            {"message": "Camera not found"},
            status=status.HTTP_404_NOT_FOUND,
        )

    return StreamingHttpResponse(
        generate_frames(cam.rstp_url),
        content_type="multipart/x-mixed-replace; boundary=frame",
    )


@api_view(["DELETE"])
def DeleteCameras(request, cam_id):
    cam = CreateCamera.objects.filter(Cam_id=cam_id).first()
    if cam is None:
        return Response(
            {"message": "Camera not exists"},
            status=status.HTTP_400_BAD_REQUEST,
        )

    camera_flags.pop(cam_id, None)
    running_cameras.pop(cam_id, None)
    cam.delete()
    return Response({"message": "Camera deleted"})


@api_view(["GET"])
def start_camera(request, cam_id):
    cam = CreateCamera.objects.filter(Cam_id=cam_id).first()
    if cam is None:
        return Response(
            {"message": "Camera not found"},
            status=status.HTTP_404_NOT_FOUND,
        )

    worker = running_cameras.get(cam_id)
    if worker is not None and worker.is_alive():
        return Response({"message": "Camera already running"})

    camera_flags[cam_id] = True
    worker = threading.Thread(
        target=runner,
        args=(cam.rstp_url, cam_id),
        daemon=True,
    )
    worker.start()
    running_cameras[cam_id] = worker

    return Response({"message": f"Camera {cam_id} started successfully"})


@api_view(["GET"])
def stop_camera(request, cam_id):
    if not camera_flags.get(cam_id):
        running_cameras.pop(cam_id, None)
        return Response({"message": "Camera not running"})

    camera_flags[cam_id] = False
    running_cameras.pop(cam_id, None)
    return Response({"message": "Camera stopped"})


@api_view(["GET"])
def stop_all_cameras(request):
    active_camera_ids = [cam_id for cam_id, is_running in camera_flags.items() if is_running]
    if not active_camera_ids:
        running_cameras.clear()
        return Response({"message": "No cameras running"})

    for cam_id in active_camera_ids:
        camera_flags[cam_id] = False

    running_cameras.clear()
    return Response({"message": "All cameras stopped and cleared"})


@api_view(['GET'])
def Computational(request, cam_id):
    record = Persons.objects.filter(Cam_ids_id=cam_id).order_by('-created').first()
    if not record:
        return JsonResponse({"error": "No data found"})
    past_person = record.previous
    current_person = record.count
    result = calculate_people(past_person, current_person)
    return JsonResponse(result)

def calculate_people(past_person, current_person, total_person=0):
    entered_person = 0
    removed_person = 0

    if current_person > past_person:
        entered_person = current_person - past_person
    elif current_person < past_person:
        removed_person = past_person - current_person

    total_person += entered_person

    return {
        "past_person": past_person,
        "present_person": current_person,
        "entered_person": entered_person,
        "removed_person": removed_person,
        "total_person": total_person
    }