from datetime import datetime, date, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy.event.base import slots_dispatcher
from app.config import settings
from app.models import WorkingHours, Appointment
from app.enums import AppointmentStatus


def get_available_slots(doctor_id: str, target_date: date, working_hours: list[WorkingHours], existing_appointments: list[Appointment], now: datetime) -> list[dict]:
    tzone = ZoneInfo(settings.clinic_tz)
    slot = []
    now_clinic = now.astimezone(tzone)
    lead_time_threshold = now_clinic + timedelta(minutes=settings.booking_lead_minutes)

    day_blocks = [workingHours for workingHours in working_hours if workingHours.weekday == target_date.weekday()]

    booked_start = {
        appointment.start_time for appointment in existing_appointments if appointment.status == AppointmentStatus.BOOKED
    }

    for block in day_blocks:
        current_date_time = datetime.combine(target_date, block.start_time, tzinfo=tzone)
        end_date_time = datetime.combine(target_date, block.end_time, tzinfo=tzone)

        while current_date_time < end_date_time:
            slot_end = current_date_time + timedelta(minutes=settings.slot_minutes)

            if current_date_time >= lead_time_threshold and current_date_time.astimezone(ZoneInfo("UTC")) not in booked_start:
                slot.append({
                    "start_time": current_date_time,
                    "end_time": slot_end
                })
            current_date_time = slot_end
    return slot
