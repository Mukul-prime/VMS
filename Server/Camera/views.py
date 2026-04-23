import threading
import importlib

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
from .models import CreateCamera
from .models import Persons
from .runtime_registry import register_rtsp, unregister_rtsp


running_cameras = {}
CAMERA_CONTROLLERS = {}


def _get_camera_controller(cam_id):
    if cam_id in CAMERA_CONTROLLERS:
        return CAMERA_CONTROLLERS[cam_id]

    module_name = f".Camera_Controller.cam{cam_id}"
    try:
        controller_module = importlib.import_module(module_name, package=__package__)
    except ModuleNotFoundError:
        return None

    CAMERA_CONTROLLERS[cam_id] = controller_module
    return controller_module


def _registry_key(cam):
    return f"{cam.Cam_id}::{cam.rstp_url}"


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

    controller = _get_camera_controller(cam_id)
    if controller is not None:
        controller.camera_flags.pop(cam_id, None)
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

    controller = _get_camera_controller(cam_id)
    if controller is None:
        return Response(
            {"message": f"No camera controller configured for camera {cam_id}"},
            status=status.HTTP_400_BAD_REQUEST,
        )

    worker = running_cameras.get(cam_id)
    if worker is not None and worker.is_alive():
        return Response({"message": "Camera already running"})

    registry_key = _registry_key(cam)
    if not register_rtsp(registry_key):
        return Response(
            {"message": "This camera is already running in another module/process"},
            status=status.HTTP_409_CONFLICT,
        )

    controller.camera_flags[cam_id] = True

    def _run_and_release():
        try:
            controller.runner(cam.rstp_url, cam_id)
        finally:
            unregister_rtsp(registry_key)

    worker = threading.Thread(target=_run_and_release, daemon=True)
    worker.start()
    running_cameras[cam_id] = worker

    return Response({"message": f"Camera {cam_id} started successfully"})


@api_view(["GET"])
def stop_camera(request, cam_id):
    controller = _get_camera_controller(cam_id)
    if controller is None:
        return Response(
            {"message": f"No camera controller configured for camera {cam_id}"},
            status=status.HTTP_400_BAD_REQUEST,
        )

    if not controller.camera_flags.get(cam_id):
        running_cameras.pop(cam_id, None)
        return Response({"message": "Camera not running"})

    controller.camera_flags[cam_id] = False
    running_cameras.pop(cam_id, None)
    cam = CreateCamera.objects.filter(Cam_id=cam_id).first()
    if cam is not None:
        unregister_rtsp(_registry_key(cam))
    return Response({"message": "Camera stopped"})


@api_view(["GET"])
def stop_all_cameras(request):
    active_camera_ids = []
    for camera_id, controller in CAMERA_CONTROLLERS.items():
        if controller.camera_flags.get(camera_id):
            active_camera_ids.append(camera_id)

    if not active_camera_ids:
        running_cameras.clear()
        return Response({"message": "No cameras running"})

    for cam_id in active_camera_ids:
        controller = _get_camera_controller(cam_id)
        if controller is not None:
            controller.camera_flags[cam_id] = False
        cam = CreateCamera.objects.filter(Cam_id=cam_id).first()
        if cam is not None:
            unregister_rtsp(_registry_key(cam))

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


@api_view(["GET"])
def camera_service_status(request):
    ids = request.query_params.getlist("ids")
    if len(ids) == 1 and "," in ids[0]:
        ids = [value.strip() for value in ids[0].split(",") if value.strip()]
    ids = [int(value) for value in ids] if ids else []

    cameras = CreateCamera.objects.all().order_by("Cam_id")
    if ids:
        cameras = cameras.filter(Cam_id__in=ids)

    camera_status = []
    selected_ids = []
    for cam in cameras:
        selected_ids.append(cam.Cam_id)
        controller = _get_camera_controller(cam.Cam_id)
        is_running = bool(controller and controller.camera_flags.get(cam.Cam_id, False))
        zoom_value = controller.get_camera_zoom(cam.Cam_id) if controller else 1.0
        worker = running_cameras.get(cam.Cam_id)
        worker_alive = bool(worker and worker.is_alive())
        latest_person_row = (
            Persons.objects.filter(Cam_ids_id=cam.Cam_id)
            .order_by("-created")
            .first()
        )
        current_count = latest_person_row.count if latest_person_row else 0
        previous_count = latest_person_row.previous if latest_person_row else 0
        people_delta = calculate_people(previous_count, current_count)

        camera_status.append(
            {
                "cam_id": cam.Cam_id,
                "cam_name": cam.Cam_name,
                "has_controller": bool(controller),
                "is_running": is_running,
                "worker_alive": worker_alive,
                "zoom": zoom_value,
                "person_count": {
                    "present": current_count,
                    "past": previous_count,
                    "added": people_delta["added_person"],
                    "removed": people_delta["removed_person"],
                    "total": people_delta["total_person"],
                },
            }
        )

    global_result = calculate_global_count(selected_ids)
    return Response(
        {
            "selected_camera_ids": selected_ids,
            "camera_status": camera_status,
            "global_count": global_result,
        }
    )


@api_view(["GET", "POST"])
def camera_zoom_control(request, cam_id):
    controller = _get_camera_controller(cam_id)
    if controller is None:
        return Response(
            {"message": f"No camera controller configured for camera {cam_id}"},
            status=status.HTTP_400_BAD_REQUEST,
        )

    cam = CreateCamera.objects.filter(Cam_id=cam_id).first()
    if cam is None:
        return Response({"message": "Camera not found"}, status=status.HTTP_404_NOT_FOUND)

    if request.method == "GET":
        return Response(
            {
                "cam_id": cam_id,
                "zoom": controller.get_camera_zoom(cam_id),
                "is_running": bool(controller.camera_flags.get(cam_id, False)),
            }
        )

    action = str(request.data.get("action", "")).strip().lower()
    zoom_value = request.data.get("zoom")

    try:
        if action == "in":
            new_zoom = controller.change_camera_zoom(cam_id, 0.1)
        elif action == "out":
            new_zoom = controller.change_camera_zoom(cam_id, -0.1)
        elif action == "reset":
            new_zoom = controller.set_camera_zoom(cam_id, 1.0)
        elif zoom_value is not None:
            new_zoom = controller.set_camera_zoom(cam_id, float(zoom_value))
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
            "is_running": bool(controller.camera_flags.get(cam_id, False)),
        }
    )
    
    
