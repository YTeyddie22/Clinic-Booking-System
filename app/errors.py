from fastapi import Request, status
from fastapi.responses import JSONResponse

class DomainError(Exception):
    def __init__(self, code: str, message: str, status_code: int):
        self.code = code
        self.message = message
        self.status_code = status_code

class SlotTakenError(DomainError):
    def __init__(self):
        super().__init__("slot_taken", "Slot is already booked for this doctor", status.HTTP_409_CONFLICT)

class OutsideWorkingHoursError(DomainError):
    def __init__(self):
        super().__init__("outside_working_hours", "Requested slot is outside the doctor's working hours", status.HTTP_422_UNPROCESSABLE_ENTITY)

class SlotInPastError(DomainError):
    def __init__(self):
        super().__init__("slot_in_past", "Cannot book a slot in the past", status.HTTP_422_UNPROCESSABLE_ENTITY)

class LeadTimeViolationError(DomainError):
    def __init__(self):
        super().__init__("lead_time_violation", "Cannot book within 60 minutes of now", status.HTTP_422_UNPROCESSABLE_ENTITY)

class AlreadyCancelledError(DomainError):
    def __init__(self):
        super().__init__("already_cancelled", "Appointment is already cancelled", status.HTTP_409_CONFLICT)

class AppointmentCancelledError(DomainError):
    def __init__(self):
        super().__init__("appointment_cancelled", "Cannot reschedule a cancelled appointment", status.HTTP_409_CONFLICT)

class NotFoundError(DomainError):
    def __init__(self, entity: str):
        super().__init__(f"{entity}_not_found", f"{entity.capitalize()} not found", status.HTTP_404_NOT_FOUND)

async def domain_exception_handler(request: Request, exc: DomainError):
    return JSONResponse(
        status_code=exc.status_code,
        content={"code": exc.code, "message": exc.message}
    )
