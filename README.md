# CompliWise Scheduler Engine

CompliWise is an automated school scheduling engine designed to generate compliant student schedules while prioritizing IEP services, intervention groups, staff availability, and scheduling constraints.

The scheduler runs as a standalone FastAPI backend with its own database and API layer.

## Features

* Automated student scheduling
* IEP service prioritization
* Service-minute compliance tracking
* Staff availability handling
* Student/staff conflict prevention
* Flex/WIN group scheduling
* Schedule proposals and validation
* Compliance flag generation
* Teacher attendance support
* Role-based access support

## Tech Stack

Backend:

* FastAPI
* SQLAlchemy
* PostgreSQL
* Alembic migrations

Frontend:

* React + TypeScript

Database:

* PostgreSQL

## Setup

Clone the repository:

```bash
git clone <repository-url>
cd scheduler-engine
```

Create a virtual environment:

```bash
python -m venv venv
```

Activate:

Windows:

```bash
venv\Scripts\activate
```

Mac/Linux:

```bash
source venv/bin/activate
```

Install dependencies:

```bash
pip install -r requirements.txt
```

Create your environment file:

Windows:

```bash
copy .env.example .env
```

Mac/Linux:

```bash
cp .env.example .env
```

Configure:

```env
DATABASE_URL=postgresql://username:password@localhost/compli_sched
SCHOOL_YEAR=2026-2027
```

## Database Setup

Run migrations:

```bash
alembic upgrade head
```

If starting with a fresh installation:

```bash
python create_database.py
```

## Running the Server

Start FastAPI:

```bash
uvicorn main:app --reload
```

API documentation:

```text
http://127.0.0.1:8000/docs
```

## Scheduling Workflow

### 1. Load Data

Import:

* Students
* Staff members
* Courses
* Service requirements
* Availability
* Scheduling rules

### 2. Generate Schedule Preview

Run the scheduler:

```text
POST /generate-schedule
```

The scheduler creates:

* Schedule entries
* Schedule proposals
* Compliance checks

No existing schedules are overwritten during preview mode.

### 3. Review Compliance

The engine checks for:

* Missing IEP minutes
* Student conflicts
* Provider conflicts
* Invalid placements
* Capacity issues

Example:

```json
{
  "student": "John Smith",
  "issue": "Missing 30 minutes of speech service",
  "severity": "high"
}
```

### 4. Publish Schedule

After review:

```text
POST /publish-schedule
```

This commits the generated schedule to the database.

---

# Scheduling Algorithm

## Current Version: Greedy Constraint Scheduler

Students are ranked by scheduling priority.

Priority order:

1. IEP students
2. Students with higher service minutes
3. Students with more required providers
4. ENL requirements
5. MTSS Tier 3
6. MTSS Tier 2

The scheduler then places required services first.

## Scheduling Rules

The engine prevents:

Student conflicts:

* A student cannot be scheduled twice in the same period.

Staff conflicts:

* A provider cannot serve multiple students/groups at the same time.

Service violations:

* Required minutes are tracked.

Capacity violations:

* Groups cannot exceed limits.

## Flex / WIN Scheduling

Flex groups are generated after required services.

The scheduler:

* Creates intervention groups
* Assigns students
* Assigns available staff
* Places groups into available periods

## Compliance Engine

The compliance engine creates flags when schedules violate rules.

Examples:

* Missing IEP minutes
* No available provider
* Staff overload
* Student conflict
* Room conflict

---

# API Endpoints

## Health Check

```http
GET /
```

Returns API status.

---

## Students

```http
GET /students
```

Returns all students.

```http
POST /students
```

Creates a student.

---

## Staff

```http
GET /staff
```

Returns available staff.

---

## Scheduler

Generate schedule:

```http
POST /generate-schedule
```

Preview schedule:

```http
GET /schedule-preview
```

Publish:

```http
POST /publish-schedule
```

---

# Future Improvements

Planned improvements:

* OR-Tools constraint optimization
* Automatic classroom assignment
* Room capacity management
* Better teacher availability parsing
* Parent-facing schedule portal
* Teacher attendance dashboard
* Historical scheduling analytics
* Multi-school support

---

# Project Goal

CompliWise aims to reduce the manual work required to build school schedules while improving compliance with student service requirements and staffing limitations.
