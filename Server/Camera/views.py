import threading

from django.db.models import Max
from django.http import StreamingHttpResponse, JsonResponse
from django.utils.timezone import now
from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.response import Response

from Camera.GlobalCalulator import calculate_global_count

from .utils import calculate_people
from . import Mark91
from .Frames import generate_frames
from .RunnerData import (
    camera_flags,
    runner,
    get_camera_zoom,
    change_camera_zoom,
    set_camera_zoom,
)
from .models import CreateCamera
from .models import Persons
from .runtime_registry import register_rtsp, unregister_rtsp


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

    response = StreamingHttpResponse(
        generate_frames(cam.rstp_url),
        content_type="multipart/x-mixed-replace; boundary=frame",
    )

    # ✅ Streaming ke liye zaroori headers
    response["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response["Pragma"] = "no-cache"
    response["X-Accel-Buffering"] = "no"
    response["Access-Control-Allow-Origin"] = "*"

    return response


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

    if not register_rtsp(cam.rstp_url):
        return Response(
            {"message": "This RTSP URL is already running in another module/process"},
            status=status.HTTP_409_CONFLICT,
        )

    camera_flags[cam_id] = True
    def _run_and_release():
        try:
            runner(cam.rstp_url, cam_id)
        finally:
            unregister_rtsp(cam.rstp_url)

    worker = threading.Thread(target=_run_and_release, daemon=True)
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
    cam = CreateCamera.objects.filter(Cam_id=cam_id).first()
    if cam is not None:
        unregister_rtsp(cam.rstp_url)
    return Response({"message": "Camera stopped"})


@api_view(["GET"])
def stop_all_cameras(request):
    active_camera_ids = [cam_id for cam_id, is_running in camera_flags.items() if is_running]
    if not active_camera_ids:
        running_cameras.clear()
        return Response({"message": "No cameras running"})

    for cam_id in active_camera_ids:
        camera_flags[cam_id] = False
        cam = CreateCamera.objects.filter(Cam_id=cam_id).first()
        if cam is not None:
            unregister_rtsp(cam.rstp_url)

    running_cameras.clear()
    return Response({"message": "All cameras stopped and cleared"})
@api_view(['GET'])
def Computational(request, cam_id):

    record = Persons.objects.filter(
        Cam_ids_id=cam_id
    ).order_by('-created').first()

    if not record:
        return JsonResponse({"error": "No data found"})

    past_person = record.previous   # 🔥 yahi sahi hai
    current_person = record.count

    result = calculate_people(past_person, current_person)

    return JsonResponse(result)


@api_view(["GET", "POST"])
def mutltioutput_computational(request):
    if request.method == "GET":
        
        ids = request.query_params.getlist("ids")
        if len(ids) == 1 and "," in ids[0]:
            ids = [value.strip() for value in ids[0].split(",") if value.strip()]
    else:
        ids = request.data.get("ids", [])

    ids = [int(value) for value in ids] if ids else []
    result = calculate_global_count(ids)
    return JsonResponse(result)


@api_view(["GET", "POST"])
def camera_zoom_control(request, cam_id):
    cam = CreateCamera.objects.filter(Cam_id=cam_id).first()
    if cam is None:
        return Response({"message": "Camera not found"}, status=status.HTTP_404_NOT_FOUND)

    if request.method == "GET":
        return Response(
            {
                "cam_id": cam_id,
                "zoom": get_camera_zoom(cam_id),
                "is_running": bool(camera_flags.get(cam_id, False)),
            }
        )

    action = str(request.data.get("action", "")).strip().lower()
    zoom_value = request.data.get("zoom")

    try:
        if action == "in":
            new_zoom = change_camera_zoom(cam_id, 0.1)
        elif action == "out":
            new_zoom = change_camera_zoom(cam_id, -0.1)
        elif action == "reset":
            new_zoom = set_camera_zoom(cam_id, 1.0)
        elif zoom_value is not None:
            new_zoom = set_camera_zoom(cam_id, float(zoom_value))
        else:
            return Response(
                {
                    "message": "Provide action=in|out|reset or zoom=<number>",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
    except (TypeError, ValueError):
        return Response({"message": "Invalid zoom value"}, status=status.HTTP_400_BAD_REQUEST)

    return Response(
        {
            "message": "Zoom updated",
            "cam_id": cam_id,
            "zoom": new_zoom,
            "is_running": bool(camera_flags.get(cam_id, False)),
        }
    )
