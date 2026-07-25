# CompliWise Scheduler Engine

CompliWise is an automated school scheduling engine that generates compliant student schedules while prioritizing IEP services, intervention groups, staff availability, and district scheduling constraints.

It runs as a standalone FastAPI backend with its own database and API layer, and is designed to reduce the manual work of building master schedules while improving compliance with student service requirements and staffing limits.

## Table of Contents

- [Features](#features)
- [Tech Stack](#tech-stack)
- [Getting Started](#getting-started)
- [Scheduling Workflow](#scheduling-workflow)
- [Scheduling Algorithm](#scheduling-algorithm)
- [Compliance Engine](#compliance-engine)
- [API Reference](#api-reference)
- [Roadmap](#roadmap)

## Features

- Automated student scheduling
- IEP service prioritization
- Service-minute compliance tracking
- Staff availability handling
- Student/staff conflict prevention
- Flex/WIN group scheduling
- Schedule proposals and validation (preview before publish)
- Compliance flag generation
- Teacher attendance support
- Role-based access support

## Tech Stack

| Layer      | Technology                     |
|------------|---------------------------------|
| Backend    | FastAPI, SQLAlchemy             |
| Database   | PostgreSQL, Alembic migrations  |
| Frontend   | React + TypeScript              |

## Getting Started

### Prerequisites

- Python 3.10+
- PostgreSQL
- Node.js (for the frontend, if running locally)

### 1. Clone the repository

```bash
git clone <repository-url>
cd CompliWise
```

### 2. Create and activate a virtual environment

```bash
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

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Configure environment variables

**Windows**
```bash
copy .env.example .env
```

**Mac/Linux**
```bash
cp .env.example .env
```

Then edit `.env`:

```env
DATABASE_URL=postgresql://username:password@localhost/compliwise_db
SCHOOL_YEAR=2026-2027
```

### 5. Run database migrations

```bash
alembic upgrade head
```

### 6. Start the server

```bash
uvicorn main:app --reload
```

Interactive API docs will be available at:

```text
http://127.0.0.1:8000/docs
```

## Scheduling Workflow

### 1. Load data

Import the following before generating a schedule:

- Students
- Staff members
- Courses
- Service requirements
- Availability
- Scheduling rules

### 2. Generate a schedule preview

```http
POST /generate-schedule
```

This creates schedule entries, schedule proposals, and compliance checks without overwriting any existing schedules — nothing is committed until you publish.

### 3. Review compliance

The engine flags issues such as:

- Missing IEP minutes
- Student conflicts
- Provider conflicts
- Invalid placements
- Capacity issues

Example flag:

```json
{
  "student": "John Smith",
  "issue": "Missing 30 minutes of speech service",
  "severity": "high"
}
```

### 4. Publish the schedule

```http
POST /publish-schedule
```

This commits the generated schedule to the database.

## Scheduling Algorithm

**Current version:** Greedy Constraint Scheduler

Students are ranked by priority, and required services are placed first in that order:

1. IEP students
2. Students with higher service minutes
3. Students with more required providers
4. ENL requirements
5. MTSS Tier 3
6. MTSS Tier 2

### Rules enforced

- **Student conflicts** — a student cannot be scheduled twice in the same period
- **Staff conflicts** — a provider cannot serve multiple students/groups at the same time
- **Service violations** — required minutes are tracked and enforced
- **Capacity violations** — groups cannot exceed their defined limits

### Flex / WIN scheduling

Flex and WIN groups are generated after required services are placed. The scheduler:

1. Creates intervention groups
2. Assigns students
3. Assigns available staff
4. Places groups into open periods

## Compliance Engine

The compliance engine raises flags whenever a generated schedule violates a rule, including:

- Missing IEP minutes
- No available provider
- Staff overload
- Student conflict
- Room conflict

## API Reference

### Health

```http
GET /
```
Returns API status.

### Students

```http
GET /students
```
Returns all students.

```http
POST /students
```
Creates a student.

### Staff

```http
GET /staff
```
Returns available staff.

### Scheduler

```http
POST /generate-schedule
```
Generates a schedule preview.

```http
GET /schedule-preview
```
Retrieves the current schedule preview.

```http
POST /publish-schedule
```
Publishes the generated schedule.

## Roadmap

- [ ] OR-Tools constraint optimization
- [ ] Automatic classroom assignment
- [ ] Room capacity management
- [ ] Better teacher availability parsing
- [ ] Teacher attendance dashboard
- [ ] Historical scheduling analytics
- [ ] Absense tracker for Teachers

## Project Goal

CompliWise aims to reduce the manual work required to build school schedules while improving compliance with student service requirements and staffing constraints.