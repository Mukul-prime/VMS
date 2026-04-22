import threading


from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework import status


from ObjectDetectors import Ghost
from ObjectDetectors.Radar import runner as run_radar_detection
from ObjectDetectors.Radar import stop_runner as stop_radar_runner
from ObjectDetectors.models import ObjectDetector, verify_data
from Camera.models import CreateCamera
from Camera.runtime_registry import register_rtsp, unregister_rtsp

running_cameras = {}
radar_port_seed = 9100


def _canonical_name(name: str) -> str:
    return "".join(ch for ch in str(name).strip().lower() if ch.isalnum())


def _normalize_cam_id(cam_id):
    return str(cam_id).strip() if cam_id is not None else None


def _session_key(cam_id, object_name):
    return f"{_normalize_cam_id(cam_id)}:{_canonical_name(object_name)}"


def _sessions_for_cam(cam_id):
    cam_key = _normalize_cam_id(cam_id)
    return [(key, data) for key, data in running_cameras.items() if data.get("cam_id") == cam_key]


def _start_camera_worker(cam, cam_id, object_name):
    global radar_port_seed
    cam_key = _normalize_cam_id(cam_id)
    run_key = _session_key(cam_id, object_name)
    if run_key in running_cameras:
        return False, f"Camera {cam_id} already running for object '{object_name}'", status.HTTP_200_OK, None

    if not _sessions_for_cam(cam_key) and not register_rtsp(cam.rstp_url):
        return False, "This RTSP URL is already running in another module/process", status.HTTP_409_CONFLICT, None

    radar_port_seed += 1
    allocated_port = radar_port_seed

    def _run_and_release():
        try:
            # Radar runner manages its own detection loop and stop control.
            run_radar_detection(cam.rstp_url, cam_id, target_object_name=object_name, session_key=run_key)
        finally:
            session = running_cameras.pop(run_key, None)
            if session is not None and not _sessions_for_cam(cam_key):
                unregister_rtsp(cam.rstp_url)

    thread = threading.Thread(target=_run_and_release, daemon=True)
    thread.start()

    running_cameras[run_key] = {
        "thread": thread,
        "cam_id": cam_key,
        "object_name": _canonical_name(object_name),
        "rtsp_url": cam.rstp_url,
        "port": allocated_port,
    }
    return True, f"Camera {cam_id} started for object '{object_name}'", status.HTTP_200_OK, allocated_port


def _stop_workers(worker_items):
    stopped_count = 0
    grouped_by_cam = {}
    for run_key, data in worker_items:
        grouped_by_cam.setdefault(data.get("cam_id"), []).append((run_key, data))
        stop_radar_runner(run_key)
        thread = data.get("thread")
        if thread is not None:
            thread.join(timeout=2.0)
        running_cameras.pop(run_key, None)
        stopped_count += 1
    for _, sessions in grouped_by_cam.items():
        if not sessions:
            continue
        sample = sessions[0][1]
        cam_id = sample.get("cam_id")
        if not _sessions_for_cam(cam_id):
            unregister_rtsp(sample.get("rtsp_url"))
    return stopped_count


def _validate_object_name(object_name):
    if not object_name:
        return False, "object_name is required", status.HTTP_400_BAD_REQUEST

    normalized_name = _canonical_name(object_name)
    object_exists = any(
        _canonical_name(db_name) == normalized_name
        for db_name in ObjectDetector.objects.values_list("Name", flat=True)
    )
    if not object_exists:
        return False, "Sorry, object not found in DB. Check it again.", status.HTTP_400_BAD_REQUEST
    return True, "", status.HTTP_200_OK


@api_view(["GET"])
def start_camera(request):
    cam_id = request.query_params.get("cam_id") or request.data.get("cam_id")
    if cam_id is None:
        return Response({"message": "cam_id is required"}, status=status.HTTP_400_BAD_REQUEST)
    cam_id = _normalize_cam_id(cam_id)

    cam = CreateCamera.objects.filter(Cam_id=cam_id).first()
    if cam is None:
        return Response({"message": "Camera not found"}, status=status.HTTP_404_NOT_FOUND)

    object_name = request.query_params.get("object_name") or request.data.get("object_name")
    valid, message, code = _validate_object_name(object_name)
    if not valid:
        return Response({"message": message, "check": False}, status=code)

    started, message, code, port = _start_camera_worker(cam, cam_id, object_name)
    payload = {"message": message, "check": started}
    if port is not None:
        payload["port"] = port
        payload["session"] = _session_key(cam_id, object_name)
    return Response(payload, status=code)


@api_view(["GET", "POST"])
def get_object_total_count(request):
    object_name = request.query_params.get("object_name") or request.data.get("object_name")
    if not object_name:
        return Response(
            {"message": "object_name is required", "check": False},
            status=status.HTTP_400_BAD_REQUEST,
        )

    normalized_name = _canonical_name(object_name)
    obj_ref = None
    for obj in ObjectDetector.objects.all():
        if _canonical_name(obj.Name) == normalized_name:
            obj_ref = obj
            break

    if obj_ref is None:
        return Response(
            {"message": "Sorry, object not found in DB. Check it again.", "check": False},
            status=status.HTTP_400_BAD_REQUEST,
        )

    cam_id = request.query_params.get("cam_id") or request.data.get("cam_id")
    query = verify_data.objects.filter(ObjectRef=obj_ref, Verified=True)
    if cam_id:
        query = query.filter(CamRef_id=cam_id)

    camera_wise = [{"cam_id": item.CamRef_id, "count": int(item.count)} for item in query]
    total_count = sum(item["count"] for item in camera_wise)

    return Response(
        {
            "check": True,
            "object_name": obj_ref.Name,
            "total_count": total_count,
            "camera_wise": camera_wise,
            "camera_considered": cam_id if cam_id else "active_camera_data",
        }
    )
@api_view(['POST'])
def create_objects(request):
    message =""
    check = None
    if ObjectDetector.objects.filter(Name=request.data['Name']).exists():
       return  Response({
           "message" : "Object with this Name already exists",
       "check" : False

       })
    serializer = Ghost.ObjectDetectors(data=request.data)
    if serializer.is_valid():
        serializer.save()
        return Response({
            "message" : "Object created successfully",
            "check" : True
        })


@api_view(["GET"])
def stop_camera(request):
    if not running_cameras:
        return Response({"message": "No cameras running", "stopped_count": 0})
    cam_id = request.query_params.get("cam_id") or request.data.get("cam_id")
    object_name = request.query_params.get("object_name") or request.data.get("object_name")
    if cam_id:
        cam_key = _normalize_cam_id(cam_id)
        if object_name:
            run_key = _session_key(cam_id, object_name)
            data = running_cameras.get(run_key)
            if data is None:
                return Response({"message": f"Camera {cam_id} with object '{object_name}' is not running", "stopped_count": 0})
            stopped_count = _stop_workers([(run_key, data)])
            return Response({"message": f"Camera {cam_id} stopped for object '{object_name}'", "stopped_count": stopped_count})
        cam_sessions = _sessions_for_cam(cam_key)
        if not cam_sessions:
            return Response({"message": f"Camera {cam_id} is not running", "stopped_count": 0})
        stopped_count = _stop_workers(cam_sessions)
        return Response({"message": f"Camera {cam_id} stopped", "stopped_count": stopped_count})

    stopped_count = _stop_workers(list(running_cameras.items()))
    return Response({"message": "All cameras stopped", "stopped_count": stopped_count})


@api_view(["GET"])
def stop_all_cameras(request):
    stopped_count = _stop_workers(list(running_cameras.items()))
    return Response({"message": "All cameras stopped", "stopped_count": stopped_count})

