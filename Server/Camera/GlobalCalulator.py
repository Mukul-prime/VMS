
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
from Camera.custom_code.Calculatorsperosnmax import (
    get_past_person_global_count,
    get_present_person_global_count,
)


def calculate_global_count(ids):
    # Opposite camera logic:
    # max(1,3) + max(5,4) + cam2 + cam6
    past_person_global_count = get_past_person_global_count(ids=ids)
    present_person_global_count = get_present_person_global_count(ids=ids)

    result = calculate_people(past_person_global_count, present_person_global_count)
    removed_person_global_count = result["removed_person"]
    added_person_global_count = result["added_person"]
    total_person_global_count = result["total_person"]

    return {
        "removed_person_global_count": removed_person_global_count,
        "added_person_global_count": added_person_global_count,
        "total_person_global_count": total_person_global_count,
        "past_person_global_count": past_person_global_count,
        "present_person_global_count": present_person_global_count
    }


# test
