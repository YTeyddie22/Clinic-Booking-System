## System Design

### Scenario

A  clinic with 5 doctors. Patients book 30-minute appointments online, per doctor, per day. Each doctor has a set of working hours. Once a slot is booked, it cannot be booked again. Patients can cancel and reschedule.

### Stack

| Concern | Choice | Why |
|---|---|---|
| Framework | **FastAPI** (Python 3.11, async) | Pydantic validation maps to the "meaningful errors + correct status codes" requirement. Also has auto OpenAPI docs. |
| Database | **PostgreSQL** | Real concurrency semantics; the partial unique index is the correctness backbone. |
| ORM | SQLAlchemy 2.x (async) + **Alembic** | Migrations are a deployment requirement on Railway. |
| Auth | JWT (`python-jose`) + argon2 (`pwdlib`) | Standard FastAPI pattern; partial implementation (see §1.4.5). |
| Tests | pytest + pytest-asyncio + httpx AsyncClient | Fast; pure-logic tests need no external services. |
| Deploy | **Railway** (web + Postgres plugin) | Native GitHub integration; "deploy on merge" and "wait for CI" built in. |
| CI | **GitHub Actions** | Runs pytest on every PR and on push to `master`. |
| Container | Dockerfile (multi-stage) | Railway builds from it; Alembic runs at container start. |

### Data model

~~~text
User                      # partial auth (Not in scope but good to consider)
  id              UUID PK
  email           str UNIQUE
  hashed_password str
  role            enum('admin','doctor','patient')
  created_at      timestamptz

Patient                   # Not in scope but important to have
  id              UUID PK
  full_name       str
  email           str UNIQUE
  phone           str nullable
  created_at      timestamptz

Doctor
  id              UUID PK
  name            str
  specialty       str nullable
  created_at      timestamptz

WorkingHours   
  id              UUID PK
  doctor_id       FK -> Doctor
  weekday         int  (0=Mon .. 6=Sun)
  start_time      time
  end_time        time
  UNIQUE (doctor_id, weekday, start_time)

Appointment
  id                  UUID PK
  doctor_id           FK -> Doctor
  patient_id          FK -> Patient
  start_time          timestamptz (UTC)
  end_time            timestamptz
  status              enum('BOOKED','CANCELLED','RESCHEDULED')
  cancellation_reason text nullable
  cancelled_at        timestamptz nullable
  rescheduled_from_id UUID FK -> Appointment nullable
  created_at          timestamptz
  updated_at          timestamptz

  PARTIAL UNIQUE INDEX ux_appt_active_slot
    ON Appointment (doctor_id, start_time)
    WHERE status = 'BOOKED';
~~~

**Invariants**

- Only `status='BOOKED'` occupies a slot. `CANCELLED` and `RESCHEDULED` are  states that free the slot.
- `end_time = start_time + SLOT_MINUTES` (30, config constant).
- All times stored UTC; all business-day math done in `CLINIC_TZ=Africa/Nairobi`.

### Decisions and trade-offs

#### Double-booking prevention — partial unique index

- **Chosen:** `UNIQUE (doctor_id, start_time) WHERE status='BOOKED'`.
- **Why:** correctness under concurrency; CANCELLED/RESCHEDULED slots auto-free because they fall outside the index.
- **Rejected:** app-level SELECT-then-INSERT (race); unique on `(doctor_id, start_time)` (blocks re-booking a cancelled slot).
- The application layer validates first for 409s; the index is the last line of defense.

#### Reschedule is append-only

- Old row → `status='rescheduled'` (terminal; slot freed).
- New row → `status='booked'` with `rescheduled_from_id` = old id.
- Reuses the same validation path as a fresh booking.
- Rescheduling a cancelled appointment → 409.
- **Why:** preserves history for audit; keeps validation logic DRY.

#### Working hours as rows, not a JSON blob

- `WorkingHours(doctor_id, weekday, start_time, end_time)`, multiple rows per day allowed (future: The doctors can have lunch breaks).
- **Why:** queryable, validatable, natural extension point.
- **Trade-off:** overlaps not DB-enforced; validated at seed time. Postgres `EXCLUDE` on a `tstzrange` is the future upgrade.

#### Patient model added (out of scope)

- `Appointment.patient_id` is a FK to `Patient`.
- No Patient CRUD endpoints in the required API. The bonus `GET /patients/{id}/appointments` and evaluator seeding need a real table.
- **Why include it:** the bonus endpoint references `patients/{id}`; a string/blob id would be dishonest to the data model. Documented as "modeled for completeness; endpoints out of scope."

#### Partial auth

- **Included:** `User` table, `POST /auth/login` (JWT), `get_current_user` dependency, seeded admin user.
- **Not enforced** on the four required booking endpoints nor the bonus `GET /patients/{id}/appointments`.
- **Why:** the assessment's required endpoints must be testable by the evaluator without credentials. Auth machinery exists and is one `Depends(get_current_user)` away from enforcement per route — documented as a next step.
- **Trade-off:** a deliberate mismatch between "production-ready" and "assessment-testable." Documented, not accidental

#### Timezone

- Store UTC. Hardcode `CLINIC_TZ=Africa/Nairobi` (EAT). Multi-clinic / multi-TZ is out of scope and noted.

#### Lead-time buffer (bonus)

- `BOOKING_LEAD_TIME_MINUTES=60`. Enforced in both the booking validator and availability generation, so availability never shows a slot you cannot book.

### Components

~~~text
app/
  main.py                # app factory + lifespan: alembic upgrade head, seed admin
  config.py              # pydantic-settings: DATABASE_URL, SECRET_KEY, CLINIC_TZ,
                         #   SLOT_MINUTES, BOOKING_LEAD_MINUTES
  db.py                  # async engine + session factory + get_db
  models.py              # User, Patient, Doctor, WorkingHours, Appointment
  schemas.py             # Pydantic request/response DTOs
  enums.py               # AppointmentStatus, UserRole
  security.py            # password hashing, JWT create/verify, get_current_user
  routers/
    auth.py              # POST /auth/login
    doctors.py           # GET /doctors/{id}/availability
    appointments.py      # POST /appointments, PATCH cancel, PATCH reschedule
    patients.py          # GET /patients/{id}/appointments  (bonus)
  services/
    availability.py      # pure slot generation (unit-testable, no DB)
    booking.py           # book / cancel / reschedule rules
  errors.py              # domain exceptions -> HTTP handlers
alembic/versions/…       # initial migration incl. partial index via postgresql_where
tests/
  conftest.py
  test_availability.py
  test_booking.py
  test_auth.py
  test_patients.py
Dockerfile
docker-compose.yml
railway.json             # healthcheck + start command hints
.github/workflows/ci.yml # pytest on PR + push to master
README.md
~~~

**Principles**

- Routes are thin (parse → call service → translate exceptions to HTTP).
- `availability.py` is pure functions → most tests need no DB.
- Domain exceptions in `errors.py` map uniformly to 409/422/404.

### Error model

Central mapping from domain exceptions to HTTP responses. Every error body:

~~~json
{ "code": "<machine_code>", "message": "<human_message>" }
~~~

| Situation | Code | Machine code | Message |
|---|---|---|---|
| Slot already booked | 409 | `slot_taken` | Slot is already booked for this doctor |
| Outside working hours | 422 | `outside_working_hours` | Requested slot is outside the doctor's working hours |
| Slot in the past | 422 | `slot_in_past` | Cannot book a slot in the past |
| Within lead-time buffer | 422 | `lead_time_violation` | Cannot book within 60 minutes of now |
| Cancel an already-cancelled appt | 409 | `already_cancelled` | Appointment is already cancelled |
| Reschedule a cancelled appt | 409 | `appointment_cancelled` | Cannot reschedule a cancelled appointment |
| Missing cancel reason | 422 | `reason_required` | Cancellation reason is required |
| Doctor not found | 404 | `doctor_not_found` | Doctor not found |
| Appointment not found | 404 | `appointment_not_found` | Appointment not found |
| Malformed body / bad date | 422 | Pydantic default | (field-level detail) |
| Unauthorised (when auth enforced) | 401 | `unauthorized` | Not authenticated |

Rationale for 409 vs 422: 409 = state conflict (someone else got the slot; you cancelled twice). 422 = semantically invalid but well-formed (bad time, inside buffer). Documented so the evaluator sees it is intentional.

### API surface (Section 2 preview)

| Method | Path | Required? |
|---|---|---|
| POST | `/appointments` | required |
| GET | `/doctors/{id}/availability?date=YYYY-MM-DD` | required |
| PATCH | `/appointments/{id}/cancel` | required |
| PATCH | `/appointments/{id}/reschedule` | required |
| GET | `/patients/{id}/appointments` | bonus |
| POST | `/auth/login` | partial auth |
| GET | `/health` | Railway check |

### Deployment

- **Service `web`:** Dockerfile build; start command `alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port $PORT`; healthcheck `/health`; trigger branch `master`.
- **Service `postgres`:** Railway plugin. `DATABASE_URL` wired via `${{Postgres.DATABASE_URL}}`. `config.py` rewrites `postgres://` → `postgresql+asyncpg://`.
- **CI gate:** GitHub Actions runs pytest on PR and push to `master`. Railway "Wait for CI" enabled → merge to `master` deploys only after tests pass.
- **Auto-deploy on merge:** Railway trigger branch `master` + autodeploy. Merging is the deploy.
- **Secrets:** `SECRET_KEY`, admin seed credentials as Railway env vars.
- **Public URL:** filled in Section 3.

### Known limitations / next steps

- Required booking endpoints unauthenticated by design (see §1.4.5).
- No Patient CRUD endpoints; Patient modeled but not exposed.
- Working-hours overlaps validated at seed time only.
- Single clinic timezone.
- No rate limiting, no pagination on the bonus endpoint.
- No soft-delete; audit preserved via status + `rescheduled_from_id` chain.
- Future: Postgres `EXCLUDE` constraint on working-hour ranges; per-doctor lead-time override; multi-clinic tenancy.

### Deployment & CI/CD

- **Live Application URL:** https://clinic-booking-system-production-940b.up.railway.app/docs
- **Deploy Branch:** `master`

### CI/CD Pipeline Description
- **GitHub Actions (CI):** The pipeline (`.github/workflows/ci.yml`) runs the `pytest` test suite on every pull request and push to the `master` branch. It provisions a temporary PostgreSQL service container to execute database-dependent tests.
- **Railway (CD):** Railway is configured to auto-deploy from the `master` branch. Once the GitHub Actions workflow passes, Railway builds the Docker image and deploys the new version.
- **Automated Migrations:** The deployment uses a custom `Dockerfile`. Upon startup, the container automatically runs `alembic upgrade head` to apply pending database migrations to the Railway PostgreSQL instance before starting the FastAPI server with Uvicorn.

---

## Section 4 — AI Reflection

**1. What did you use AI for across the four sections?**
I used AI to scaffold the initial FastAPI boilerplate, generate the SQLAlchemy models, and troubleshoot environment-specific errors (such as Alembic's asyncpg driver conflicts, Pydantic v2 serialization issues, and Railway's builder configuration) I also used it to write up parts of the documentation that seemed off.

**2. Give one example where an AI suggestion improved your work. What did you prompt it with?**
I prompted the AI with: "How should I design the database schema to prevent double-booking at the DB level, not just the application level?". This was to uphold the industry standard of fat models and thin controllers. It suggested using a **PostgreSQL partial unique index** `(doctor_id, start_time) WHERE status = 'booked'`. This was a massive improvement because it guarantees data integrity even under concurrent requests, which app-level validation alone cannot do.

**3. Give one example where AI output was wrong or incomplete and how you caught it.**
When generating the Alembic migration, the AI forgot to include the `postgresql_where` clause for the partial unique index. I caught it by reviewing the generated migration file and testing the schema in pgAdmin to ensure the index was applied. The AI wrote a broken relationship mapping between `Doctor` and `WorkingHours` that caused the app to crash on startup; I caught it by reading the Railway deployment logs and reordering the class definitions.

**4. Name two decisions you made without AI. Why did you trust your own judgment there?**
- **Append-only reschedules:** I decided to keep old appointments as `rescheduled` and create a new appointment row, rather than just updating the `start_time` in place. I trusted this judgment because preserving the audit trail is critical in healthcare systems.
- **Partial Auth Scope:** I chose to implement the JWT utility functions and a `User` table, but did not enforce authentication on the booking endpoints. I did this because the assessment prioritized testability by the evaluator over production-level security.
