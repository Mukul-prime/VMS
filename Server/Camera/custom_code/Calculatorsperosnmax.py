from django.utils.timezone import now

from Camera.models import Persons


# Opposite side camera pairs:
# (1, 3), (5, 4)
# Single side cameras:
# 2, 6
PAIR_GROUPS = [(1, 3), (5, 4)]
SINGLE_CAMERAS = [2, 6]


def _camera_latest_map(ids=None):
    today = now().date()
    rows = Persons.objects.filter(date=today)
    if ids:
        rows = rows.filter(Cam_ids_id__in=ids)
    return {row.Cam_ids_id: row for row in rows}


def _pair_value(camera_map, pair, field_name):
    a, b = pair
    a_value = getattr(camera_map.get(a), field_name, 0)
    b_value = getattr(camera_map.get(b), field_name, 0)
    return max(a_value, b_value)


def _single_value(camera_map, cam_id, field_name):
    return getattr(camera_map.get(cam_id), field_name, 0)


def get_opposite_side_sum(ids=None, field_name="count"):
    camera_map = _camera_latest_map(ids=ids)

    total = 0
    for pair in PAIR_GROUPS:
        total += _pair_value(camera_map, pair, field_name)
    for cam_id in SINGLE_CAMERAS:
        total += _single_value(camera_map, cam_id, field_name)
    return int(total)


def get_present_person_global_count(ids=None):
    return get_opposite_side_sum(ids=ids, field_name="count")


def get_past_person_global_count(ids=None):
    return get_opposite_side_sum(ids=ids, field_name="previous")

