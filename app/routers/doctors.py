import uuid
from datetime import date, datetime, timezone
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from app.db import get_db
from app import schemas, errors
from app.models import Doctor, WorkingHours, Appointment
from app.services.availability import get_available_slots


router = APIRouter(prefix="/doctors", tags=["Doctors"])

@router.get("/{id}/availability", response_model=schemas.AvailabilityResponse)
async def get_doctor_availability(id: uuid.UUID, date: date = Query(...), db: AsyncSession=Depends(get_db)):
    doctor = await db.get(Doctor, id)

    if not doctor:
        raise errors.NotFoundError("doctor")

    statement_working_hours = select(WorkingHours).where(WorkingHours.doctor_id == id)
    result_working_hours = await db.execute(statement_working_hours)
    working_hours = list(result_working_hours.scalars().all())

    statement_appointments = select(Appointment).where(Appointment.doctor_id == id, Appointment.status == "BOOKED")

    result_appointments = await db.execute(statement_appointments)
    appointments = list(result_appointments.scalars().all())

    slots = get_available_slots(target_date=date, working_hours=working_hours, existing_appointments=appointments, now=datetime.now(timezone.utc))

    return schemas.AvailabilityResponse(
        doctor_id = id,
        date = date,
        available_slots = [schemas.AvailabilitySlot(**slot) for slot in slots]
    )
