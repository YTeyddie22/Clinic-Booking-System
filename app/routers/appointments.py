import uuid
from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession
from app.db import get_db
from app import schemas
from app.services import booking


router = APIRouter(prefix="/appointments", tags=["Appointments"])

@router.post("", response_model=schemas.AppointmentResponse, status_code=status.HTTP_201_CREATED)
async def create_appoointment(body: schemas.AppointmentCreate, db: AsyncSession=Depends(get_db)):
    return await booking.book_appointment(db, body.doctor_id, body.patient_id, body.start_time)

@router.patch("/{id}/cancel", response_model=schemas.AppointmentResponse)
async def cancel_appointment(id: uuid.UUID, body: schemas.AppointmentCancel, db: AsyncSession=Depends(get_db)):
    return await booking.cancel_appointment(db, id, body.reason)

@router.patch("/{id}/reschedule", response_model=schemas.AppointmentReschedule)
async def rescheduleAppointment(id:uuid.UUID, body: schemas.AppointmentReschedule, db: AsyncSession=Depends(get_db)):
    return await booking.reschedule_appointment(db, id, body.new_start_time)
