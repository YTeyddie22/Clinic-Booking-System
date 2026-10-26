import uuid
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.exc import IntegrityError
from app.models import Appointment, Doctor, Patient, WorkingHours
from app.enums import AppointmentStatus
from app.config import settings
from app import errors


async def _validate_slot(db: AsyncSession, doctor_id: uuid.UUID, start_time: datetime):
    doctor = await db.get(Doctor, doctor_id)

    if not doctor:
        raise errors.NotFoundError("doctor")

    start_utc = start_time.astimezone(timezone.utc)
    now_utc = datetime.now(timezone.utc)

    if start_utc < now_utc:
        raise errors.SlotInPastError()

    if start_utc < now_utc + timedelta(minutes=settings.booking_lead_minutes):
        raise errors.LeadTimeViolationError

    clinic_time_zone = ZoneInfo(settings.clinic_tz)
    local_date_time = start_utc.astimezone(clinic_time_zone)

    local_time = local_date_time.time()
    weekday = local_date_time.weekday()

    statement = select(WorkingHours).where(
        WorkingHours.doctor_id == doctor_id,
        WorkingHours.weekday == weekday,
        WorkingHours.start_time <= local_time,
        WorkingHours.end_time > local_time
    )
    res = await db.execute(statement)

    if not res.scalar().first():
        raise errors.OutsideWorkingHoursError()

async def book_appointment(db: AsyncSession, doctor_id: uuid.UUID, patient_id: uuid.UUID, start_time: datetime):
    await _validate_slot(db, doctor_id, start_time)

    start_utc = start_time.astimezone(timezone.utc)
    end_utc = start_utc + timedelta(minutes=settings.slot_minutes)

    '''Will need Refactoring later'''

    appointment = Appointment(
        doctor_id = doctor_id,
        patient_id = patient_id,
        start_time = start_utc,
        end_time = end_utc,
        status = AppointmentStatus.BOOKED
    )

    db.add(appointment)

    try:
        await db.commit()
        await db.refresh(appointment)
        return appointment

    except IntegrityError as error:
        await db.rollback()
        if "ux_appt_active_slot" in str(error.orig):
            raise errors.SlotTakenError()
        raise error


async def cancel_appointment(db: AsyncSession, appointment_id: uuid.UUID, reason: str):
    appointment = await db.get(Appointment, appointment_id)

    if not appointment:
        raise errors.NotFoundError("appointment")

    if appointment.status == AppointmentStatus.CANCELLED:
        raise errors.AlreadyCancelledError()

    appointment.status = AppointmentStatus.CANCELLED
    appointment.cancellation_reason = reason

    appointment.cancelled_at = datetime.now(timezone.utc)

    await db.commit()
    return appointment


async def reschedule_appointment(db: AsyncSession, old_appointment_id: uuid.UUID, new_start_time: datetime):
    old_appointment = await db. get(Appointment, old_appointment_id)

    if not old_appointment:
        raise errors.NotFoundError("appointment")

    if old_appointment.status == AppointmentStatus.CANCELLED:
        raise errors.AppointmentCancelledError()

    await _validate_slot(db, old_appointment_id, new_start_time)
    old_appointment.status = AppointmentStatus.RESCHEDULED

    new_start_utc = new_start_time.astimezone(timezone.utc)

    '''Will need Refactoring later'''

    new_appointment = Appointment(
        doctor_id = old_appointment.doctor_id,
        patient_id = old_appointment.patient_id,
        start_time = new_start_utc,
        end_time = new_start_utc + timedelta(minutes=settings.slot_minutes),
        status = AppointmentStatus.BOOKED,
        rescheduled_from_id = old_appointment.id
    )

    db.add(new_appointment)

    try:
        await db.commit()
        await db.refresh(new_appointment)
        return new_appointment
    except IntegrityError as error:
        if "ux_appt_active_slot" in str(error.orig):
            raise errors.SlotTakenError()
        raise error
