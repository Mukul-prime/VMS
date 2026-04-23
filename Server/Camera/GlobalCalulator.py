
import os
import sys
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(BASE_DIR)
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'IronHeart.settings')
import django
django.setup()
from django.utils.timezone import now
from Camera.models import Persons
from Camera.utils import calculate_people


def calculate_global_count(ids):
    removed_person_global_count = 0
    added_person_global_count = 0
    total_person_global_count = 0
    past_person_global_count = 0
    present_person_global_count = 0

    today = now().date()

    cams = Persons.objects.filter(date=today)
    if ids:
        cams = cams.filter(Cam_ids_id__in=ids)

    for cam in cams:
        count = cam.count
        previous = cam.previous

        result = calculate_people(previous, count)
        removed_person_global_count += result["removed_person"]
        added_person_global_count += result["added_person"]
        total_person_global_count += result["total_person"]
        past_person_global_count += result["past_person"]
        present_person_global_count += result["present_person"]

    return {
        "removed_person_global_count": removed_person_global_count,
        "added_person_global_count": added_person_global_count,
        "total_person_global_count": total_person_global_count,
        "past_person_global_count": past_person_global_count,
        "present_person_global_count": present_person_global_count
    }


# test
