def calculate_people(past_person, current_person):
    added_person = 0
    removed_person = 0

    if current_person > past_person:
        added_person = current_person - past_person

    elif current_person < past_person:
        removed_person = past_person - current_person

    return {
        "past_person": past_person,
        "present_person": current_person,
        "added_person": added_person,
        "removed_person": removed_person,
        "total_person": current_person
    }