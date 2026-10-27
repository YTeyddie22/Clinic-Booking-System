import uuid
from datetime import datetime, date
from pydantic import BaseModel, Field, ConfigDict
from app.enums import AppointmentStatus

class AppointmentCreate(BaseModel):
    doctor_id: uuid.UUID
    patient_id: uuid.UUID
    start_time: datetime

class AppointmentCancel(BaseModel):
    reason: str = Field(..., min_length=1, max_length=500)

class AppointmentReschedule(BaseModel):
    new_start_time: datetime

class AppointmentResponse(BaseModel):
    id: uuid.UUID
    doctor_id: uuid.UUID
    patient_id: uuid.UUID
    start_time: datetime
    end_time: datetime
    status: AppointmentStatus
    cancellation_reason: str | None
    model_config = ConfigDict(from_attributes=True)

class AvailabilitySlot(BaseModel):
    start_time: datetime
    end_time: datetime
    model_config = ConfigDict(from_attributes=True)

class AvailabilityResponse(BaseModel):
    doctor_id: uuid.UUID
    date: date
    available_slots: list[AvailabilitySlot]
    model_config = ConfigDict(from_attributes=True)
