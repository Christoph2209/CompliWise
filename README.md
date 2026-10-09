# CompliWise Scheduler Engine

CompliWise is an automated school scheduling engine that generates compliant student schedules while prioritizing IEP services, intervention groups, staff availability, and district scheduling constraints.

It is a FastAPI backend with a PostgreSQL database and a React frontend. It is designed to reduce the manual work of building master schedules while improving compliance with student service requirements and staffing limits.

## Table of Contents

- [Features](#features)
- [Tech Stack](#tech-stack)
- [Project Layout](#project-layout)
- [Getting Started](#getting-started)
- [Running with Docker](#running-with-docker)
- [Deploying](DEPLOY.md)
- [Running the Tests](#running-the-tests)
- [Roles](#roles)
- [Accounts and Passwords](#accounts-and-passwords)
- [Scheduling Workflow](#scheduling-workflow)
- [Scheduling Algorithm](#scheduling-algorithm)
- [Compliance Engine](#compliance-engine)
- [API Reference](#api-reference)
- [Roadmap](#roadmap)

## Features

- Automated whole-school scheduling from each grade's master schedule
- IEP / ENL / related-service placement (pull-out and push-in)
- Service-minute compliance tracking
- Student/staff conflict prevention
- Specials (PE / Music / Art) staffing
- Flex/WIN group scheduling
- Teacher dashboards showing their classes and their students' pull-outs
- Compliance flag generation and resolution
- CSV import with row-by-row validation before anything is saved
- Login with role-based access; each school's data is kept separate
- Audit log of logins and changes
- Password changes for staff require an admin's approval

## Tech Stack

| Layer      | Technology                         |
|------------|------------------------------------|
| Backend    | FastAPI, SQLAlchemy                |
| Database   | PostgreSQL, Alembic migrations     |
| Frontend   | React + TypeScript (Vite)          |

## Project Layout

```text
backend/
  main.py               API endpoints, login and role checks
  scheduler.py          the scheduling engine
  scheduling_core.py    master schedule (PeriodConfig) and shared constants
  compliance.py         compliance checks run on a finished schedule
  database_service.py   saves/loads scheduler data
  import_csv_data.py    CSV / Excel import
  roster_file.py        Reads CSV and .xlsx files; compliance-roster columns
  compliwise_db.py     database models
  import_csv_data.py    CSV import
  import_validation.py  CSV checks run before importing
  setup.py              first-run setup (migrations, first admin)
  alembic/              database migrations
  tests/                end-to-end tests
frontend/               React app
deploy/                 Caddyfile for the production stack
data/                   sample CSV exports
```

## Getting Started

### Prerequisites

- Python 3.10+
- PostgreSQL
- Node.js 20.19+ (for the frontend)

### 1. Clone the repository

```bash
git clone <repository-url>
cd CompliWise
```

### 2. Configure environment variables

Copy the example file to `.env` in the repo root:

**Windows**
```bash
copy .env.example .env
```

**Mac/Linux**
```bash
cp .env.example .env
```

Then edit `.env`. At minimum set:

```env
DATABASE_URL=postgresql://username:password@localhost:5432/compliwise
SESSION_SECRET=<a long random string>
```

The backend will not start without `SESSION_SECRET`. Generate one with:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

See `.env.example` for the optional settings.

### 3. Set up the backend

```bash
cd backend
python -m venv venv
```

**Windows**
```bash
venv\Scripts\activate
```

**Mac/Linux**
```bash
source venv/bin/activate
```

Then install dependencies, create the database tables, and start the server:

```bash
pip install -r requirements.txt
alembic upgrade head
uvicorn main:app --reload
```

The API runs at `http://127.0.0.1:8000`, with interactive docs at `http://127.0.0.1:8000/docs`.

### 4. Start the frontend

In a second terminal:

```bash
cd frontend
npm install
npm run dev
```

Open `http://localhost:5173`.

### 5. First-run setup

On a fresh database the app opens a setup wizard. It creates your school and the first admin account, then optionally imports your student and staff CSVs. The admin can then add more users from the Admin page.

## Running with Docker

```bash
cp .env.example .env    # then set SESSION_SECRET and the POSTGRES_* values
docker compose up --build
```

This starts Postgres, the backend on port 8000, and the frontend on port 5173, over plain HTTP. It is meant for development and demos.

For a real deployment with student data, use `docker-compose.prod.yml` instead: it adds HTTPS, keeps the database off the network and takes nightly backups. See [DEPLOY.md](DEPLOY.md).

## Running the Tests

The tests create schools and users, so point them at a **throwaway** database:

```bash
cd backend
pip install -r requirements-dev.txt
export DATABASE_URL=postgresql://user:pass@localhost/compliwise_test
export SESSION_SECRET=test
alembic upgrade head
python -m pytest tests -q
```

## Roles

| Role        | Can do                                                                  |
|-------------|-------------------------------------------------------------------------|
| `admin`     | Everything, plus user accounts, password approvals, CSV import, resets and the audit log |
| `principal` | Manage students, staff and services; generate and edit schedules        |
| `teacher`   | See their own schedule, their students, and those students' pull-outs   |
| `aide`      | Same as teacher                                                         |

Every request only sees data from the user's own school.

## Accounts and Passwords

Everyone has a **My Account** page (`/account`) with their profile and a change-password form.

- **Teachers, aides and principals** can't change their password on their own. Submitting the form sends a request to their school's admins, and the old password keeps working until an admin decides. The page shows whether the request is waiting, approved or rejected (with the admin's note), and the person can withdraw it. A new request replaces any one still waiting.
- **Admins** review requests on the **Password Requests** page (`/password-requests`). A badge in the sidebar shows how many are waiting. Approving applies the new password; rejecting leaves the old one in place. It's worth confirming with the person before approving, since a request they didn't make could mean someone else is using their account.
- **Admins change their own password directly**, with no approval step.

Safeguards:

- The current password is required to submit a request, so a computer left signed in can't be used to take over the account.
- New passwords must be at least 10 characters and different from the current one.
- The requested password is stored only as an Argon2 hash, and only while the request is pending. The hash is deleted once the request is approved, rejected or withdrawn.
- Admins only see and act on requests from their own school, and every request, approval, rejection and failed attempt is recorded in the audit log.
- When a password changes, every session that started before the change is signed out, and the person signs in again with the new password.

Upgrading an existing install: run `alembic upgrade head` to create the `password_change_requests` table. Everyone already signed in will need to sign in once more after the upgrade.

## Scheduling Workflow

### 1. Load data

Import students and staff from CSV or Excel (.xlsx) files in the setup wizard or, for an admin, any time afterwards from the **Import Students** page. Each file is checked row by row first; a file with errors is refused as a whole, and the report lists every problem.

- **Students:** ID, name, grade, homeroom, IEP status, ENL level/minutes, MTSS tier, and IEP services (`iep_services`, a JSON list).
- **Staff:** ID, name, title, grade, homeroom, and certifications (SPED, ENL, SLP, Resource Room).

A students file can also be a **compliance roster** workbook: one row per student, a placement column per core subject (`Gen Education`, `ICT`, `12:1+1`, `Special class 12:1`) and a column per service (`Speech`, `OT`, `Counseling`, `Teaching assistant`, `ENL`, `Resource room`) with cells like `2X30 group of 3`. Placements and services become IEP services on the student, the IEP flag is inferred from them, and ENL minutes are set from the ENL level. Special-class placements and teaching assistants are recorded but not scheduled yet.

> IEP minutes imported from CSV are placeholders, since exports only carry a frequency such as "2x/week". Each imported service is marked **NEEDS VERIFICATION**; check them against the IEP paperwork.

### 2. Generate a schedule

From the Generate Schedule window, review the master schedule (each grade's blocks and times) and the pull-out rules, then generate. Generation runs in the background with a progress bar:

```http
POST /schedule/generate/start
GET  /schedule/generate/status/{job_id}
```

Each generation is saved as a new **schedule run**, so earlier runs stay available for comparison.

### 3. Review compliance

The engine flags issues such as:

- Missing IEP / ENL minutes
- No qualified provider for a service
- Too many pull-outs in a day, or pull-outs too close together
- Teacher double-booked
- Class or group over capacity

Flags are listed on the Compliance page, where they can be resolved.

### 4. Adjust

Principals can edit individual entries, and get suggested open times for a service that couldn't be placed (`GET /students/{id}/services/{service_id}/suggestions`).

## Scheduling Algorithm

**Current version:** Greedy constraint scheduler

Each grade follows its own master schedule (for example 2nd grade: Math 8:20–9:20, ELA 9:20–10:30, …). Times are minutes since midnight, and every booking is a start–end interval inside one of those blocks. The school runs on a rotating A–E day cycle.

Steps:

1. **Mandated services** (IEP, ENL, related services) are placed first, hardest-to-place first (fewest legal times). Student priority breaks ties: IEP, number of services, ENL minutes, then MTSS tier. Each possible time is scored:
   - Pull-outs prefer intervention time (I-Block) and avoid core ELA/Math, and are spread across subjects.
   - Push-ins only go into the subjects allowed for that service.
   - A student keeps the same provider all week when possible.
   - ENL groups prefer students from the same homeroom. Where that would leave any student short of a session, the preference is dropped and those students are grouped across homerooms instead.
   - Once the groups are set, an ENL pull-out group whose students all share a homeroom (or a single student) becomes a push-in, as long as it falls in a subject that allows ENL push-in.
2. **Specials** — each homeroom gets its PE / Music / Art teachers.
3. **Flex / WIN groups** — built inside each grade's FLEX block.
4. **Everything else** — the rest of each student's day is filled from the master schedule.
5. **Staff schedules** — one row per teacher per class, including prep and lunch.
6. **Compliance checks** run on the result.

### Rules enforced

- **Student conflicts** — a student is never in two places at once
- **Staff conflicts** — a provider only takes students together when it is the same group
- **Pull-out limits** — maximum pull-outs per day and minimum gap between them (configurable)
- **Capacity** — groups and classes can't exceed their limits

## Compliance Engine

The compliance checks (`backend/compliance.py`) inspect a finished schedule and raise flags whenever it breaks a rule, including:

- Missing IEP / service minutes
- No available or qualified provider
- Teacher double-booked
- Class or group over capacity
- Pull-outs from blocks the rules don't allow
- Too many pull-outs per day

They can be re-run against the latest schedule with `POST /run-compliance-check`.

## API Reference

All endpoints except login and first-run setup require a logged-in session. The full, current list with request/response shapes is at `/docs` when the backend is running. Main endpoints:

| Method & path                                   | Who            | What                                       |
|-------------------------------------------------|----------------|--------------------------------------------|
| `POST /login`, `POST /logout`, `GET /me`        | anyone         | Session and current user                   |
| `GET /setup/status`, `POST /setup/initialize`   | before setup   | First-run setup                            |
| `POST /import/preview`, `POST /import/commit`   | admin          | Validate / import student and staff CSVs   |
| `POST /admin/users`                             | admin          | Create a user account                      |
| `GET /me/password-change-request`               | anyone         | Whether approval is needed, and the latest request |
| `POST /me/password`                             | anyone         | Change password (admins) or request a change (everyone else) |
| `DELETE /me/password-change-request`            | anyone         | Withdraw a pending request                 |
| `GET /admin/password-change-requests`           | admin          | Pending requests (`?status=all` for history) |
| `POST /admin/password-change-requests/{id}/approve`, `…/reject` | admin | Decide on a request |
| `GET /students`, `PUT /students/{id}`           | admin, principal | Students                                 |
| `GET/POST/PUT/DELETE /students/{id}/services…`  | admin, principal | A student's service requirements         |
| `GET /staff`, `POST /staff`, `PUT /staff/{id}`  | staff / managers | Staff members                            |
| `POST /schedule/generate/start`                 | admin, principal | Generate a schedule in the background    |
| `GET /schedule-runs`, `GET /schedule-runs/{id}` | admin, principal | Saved schedule runs                      |
| `GET /schedule`                                 | all staff      | Student schedule entries (teachers: their own plus their students' pull-outs) |
| `GET /staff-schedule`                           | all staff      | Teacher schedules (teachers: their own)    |
| `GET /me/students`                              | teacher        | The teacher's classes and students         |
| `GET /compliance-flags`, `PATCH /compliance-flags/{id}/resolve` | admin, principal | Compliance flags |
| `GET /flex_groups`                              | all staff      | Flex groups (teachers: the ones they run)  |
| `GET /audit-logs`                               | admin          | Audit log                                  |

## Roadmap

- [ ] OR-Tools constraint optimization
- [ ] Automatic classroom assignment
- [ ] Room capacity management
- [ ] Better teacher availability parsing
- [ ] Teacher attendance dashboard
- [ ] Historical scheduling analytics
- [ ] Absence tracker for teachers

## Project Goal

CompliWise aims to reduce the manual work required to build school schedules while improving compliance with student service requirements and staffing constraints.
