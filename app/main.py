from fastapi import FastAPI
from app import errors
from app.routers import appointments, doctors, patients

app = FastAPI(title="Clinic Booking API")

app.add_exception_handler(errors.DomainError, errors.domain_exception_handler)

app.include_router(appointments.router)
app.include_router(doctors.router)
app.include_router(patients.router)

@app.get("/health")
def health_check():
    return {"status": "ok"}
