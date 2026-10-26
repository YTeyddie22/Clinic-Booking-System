import uuid
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from app.db import get_db
from app import schemas
from app.models import Appointment


router = APIRouter(prefix="/patients", tags=["Patients"])

@router.get("/id}/appointments", response_model=list[schemas.AppointmentResponse])
async def get_patient_appointments(id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    statement_appointment = select(Appointment).where(Appointment.patient_id == id, Appointment.status == "booked").order_by(Appointment.start_time.asc())

    result = await db.execute(statement_appointment)
    return result.scalars().all()
