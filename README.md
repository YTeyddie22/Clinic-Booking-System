## Section 1 — System Design

### 1.1 Scenario

A  clinic with 5 doctors. Patients book 30-minute appointments online, per doctor, per day. Each doctor has a set of working hours. Once a slot is booked, it cannot be booked again. Patients can cancel and reschedule.

### 1.2 Stack

| Concern | Choice | Why |
|---|---|---|
| Framework | **FastAPI** (Python 3.11, async) | Pydantic validation maps to the "meaningful errors + correct status codes" requirement. Also has auto OpenAPI docs. |
| Database | **PostgreSQL** | Real concurrency semantics; the partial unique index is the correctness backbone. |
| ORM | SQLAlchemy 2.x (async) + **Alembic** | Migrations are a deployment requirement on Railway. |
| Auth | JWT (`python-jose`) + argon2 (`pwdlib`) | Standard FastAPI pattern; partial implementation (see §1.4.5). |
| Tests | pytest + pytest-asyncio + httpx AsyncClient | Fast; pure-logic tests need no external services. |
| Deploy | **Railway** (web + Postgres plugin) | Native GitHub integration; "deploy on merge" and "wait for CI" built in. |
| CI | **GitHub Actions** | Runs pytest on every PR and on push to `main`. |
| Container | Dockerfile (multi-stage) | Railway builds from it; Alembic runs at container start. |

### 1.3 Data model

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

### 1.4 Key decisions and trade-offs

#### 1.4.1 Double-booking prevention — partial unique index

- **Chosen:** `UNIQUE (doctor_id, start_time) WHERE status='BOOKED'`.
- **Why:** correctness under concurrency; CANCELLED/RESCHEDULED slots auto-free because they fall outside the index.
- **Rejected:** app-level SELECT-then-INSERT (race); unique on `(doctor_id, start_time)` (blocks re-booking a cancelled slot).
- The application layer validates first for 409s; the index is the last line of defense.

#### 1.4.2 Reschedule is append-only

- Old row → `status='rescheduled'` (terminal; slot freed).
- New row → `status='booked'` with `rescheduled_from_id` = old id.
- Reuses the same validation path as a fresh booking.
- Rescheduling a cancelled appointment → 409.
- **Why:** preserves history for audit; keeps validation logic DRY.

#### 1.4.3 Working hours as rows, not a JSON blob

- `WorkingHours(doctor_id, weekday, start_time, end_time)`, multiple rows per day allowed (future: The doctors can have lunch breaks).
- **Why:** queryable, validatable, natural extension point.
- **Trade-off:** overlaps not DB-enforced; validated at seed time. Postgres `EXCLUDE` on a `tstzrange` is the future upgrade.

#### 1.4.4 Patient model added (out of scope)

- `Appointment.patient_id` is a FK to `Patient`.
- No Patient CRUD endpoints in the required API. The bonus `GET /patients/{id}/appointments` and evaluator seeding need a real table.
- **Why include it:** the bonus endpoint references `patients/{id}`; a string/blob id would be dishonest to the data model. Documented as "modeled for completeness; endpoints out of scope."

#### 1.4.5 Partial auth

- **Included:** `User` table, `POST /auth/login` (JWT), `get_current_user` dependency, seeded admin user.
- **Not enforced** on the four required booking endpoints nor the bonus `GET /patients/{id}/appointments`.
- **Why:** the assessment's required endpoints must be testable by the evaluator without credentials. Auth machinery exists and is one `Depends(get_current_user)` away from enforcement per route — documented as a next step.
- **Trade-off:** a deliberate mismatch between "production-ready" and "assessment-testable." Documented, not accidental

#### 1.4.6 Timezone

- Store UTC. Hardcode `CLINIC_TZ=Africa/Nairobi` (EAT). Multi-clinic / multi-TZ is out of scope and noted.

#### 1.4.7 Lead-time buffer (bonus)

- `BOOKING_LEAD_TIME_MINUTES=60`. Enforced in both the booking validator and availability generation, so availability never shows a slot you cannot book.

### 1.5 Components

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
.github/workflows/ci.yml # pytest on PR + push to main
README.md
~~~

**Principles**

- Routes are thin (parse → call service → translate exceptions to HTTP).
- `availability.py` is pure functions → most tests need no DB.
- Domain exceptions in `errors.py` map uniformly to 409/422/404.

### 1.6 Error model

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

### 1.7 API surface (Section 2 preview)

| Method | Path | Required? |
|---|---|---|
| POST | `/appointments` | required |
| GET | `/doctors/{id}/availability?date=YYYY-MM-DD` | required |
| PATCH | `/appointments/{id}/cancel` | required |
| PATCH | `/appointments/{id}/reschedule` | required |
| GET | `/patients/{id}/appointments` | bonus |
| POST | `/auth/login` | partial auth |
| GET | `/health` | Railway check |

### 1.8 Deployment (Section 3 preview)

- **Service `web`:** Dockerfile build; start command `alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port $PORT`; healthcheck `/health`; trigger branch `main`.
- **Service `postgres`:** Railway plugin. `DATABASE_URL` wired via `${{Postgres.DATABASE_URL}}`. `config.py` rewrites `postgres://` → `postgresql+asyncpg://`.
- **CI gate:** GitHub Actions runs pytest on PR and push to `main`. Railway "Wait for CI" enabled → merge to `main` deploys only after tests pass.
- **Auto-deploy on merge:** Railway trigger branch `main` + autodeploy. Merging is the deploy.
- **Secrets:** `SECRET_KEY`, admin seed credentials as Railway env vars.
- **Public URL:** filled in Section 3.

### 1.9 Known limitations / next steps

- Required booking endpoints unauthenticated by design (see §1.4.5).
- No Patient CRUD endpoints; Patient modeled but not exposed.
- Working-hours overlaps validated at seed time only.
- Single clinic timezone.
- No rate limiting, no pagination on the bonus endpoint.
- No soft-delete; audit preserved via status + `rescheduled_from_id` chain.
- Future: Postgres `EXCLUDE` constraint on working-hour ranges; per-doctor lead-time override; multi-clinic tenancy.

### 1.10 Decisions made without AI (feeds Section 4)

1. **Partial unique index for double-booking** — a correctness-under-concurrency judgment that should be reasoned.
2. **Partial-auth scope** — implementing the machinery but  not gating the required endpoints, because the assessment prioritizes testability over production realism. A judgment call about what the brief wants.
3. **Adding the Patient model despite it being out of required scope** — honest data modeling given the bonus endpoint references `patients/{id}`.
