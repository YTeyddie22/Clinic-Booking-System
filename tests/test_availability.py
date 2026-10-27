from datetime import datetime, date, time, timezone
from app.services.availability import get_available_slots

class MockWorkingHours:
    weekday = 0
    start_time = time(9, 0)
    end_time = time(10, 0)

def test_availability_slots():
    target_date = date(2024, 1, 1)
    now_UTC= datetime(2024, 1, 1, 5, 0, tzinfo=timezone.utc)

    slots = get_available_slots( target_date=target_date, working_hours=[MockWorkingHours()], existing_appointments=[], now=now_UTC)

    assert len(slots) == 2
    assert slots[0]["start_time"].hour == 9
