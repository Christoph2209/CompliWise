# CompliSched Scheduler Engine

This is the FastAPI backend that connects to the Base44 CompliSched app.

The Base44 app stores:

- `Student`
- `StaffMember`
- `ScheduleEntry`
- `ScheduleProposal`
- `ComplianceFlag`
- `FlexGroup`
- `LegalRule`

This backend reads Base44 student/staff records, prioritizes students with IEP services first, generates schedule entries, and can write schedule proposals and compliance flags back to Base44.

## Setup

```bash
mkdir scheduler-engine
cd scheduler-engine
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

Copy `.env.example` to `.env`:

```bash
copy .env.example .env
```

Edit `.env`:

```env
BASE44_BASE_URL=https://compli-sched.base44.app/api
BASE44_API_KEY=your_real_api_key_here
SCHOOL_YEAR=2026-2027
```

## Run

```bash
uvicorn main:app --reload
```

Open:

```text
http://127.0.0.1:8000/docs
```

## Safe testing order

### 1. Confirm API is running

```text
GET /
```

### 2. Confirm Base44 connection

```text
GET /test-base44
```

Expected:

```json
{
  "success": true,
  "students_found": 123,
  "staff_found": 20
}
```

### 3. Preview priority order

```text
GET /preview-priority
```

This reads Base44 students and returns the IEP-first priority order.

It does **not** write anything back to Base44.

### 4. Generate schedule preview

```text
POST /generate-schedule
```

This generates:

- `schedule_entries`
- `schedule_proposals`
- `compliance_flags`

It does **not** save anything back to Base44.

### 5. Save generated schedule to Base44

Only run this after inspecting the preview:

```text
POST /sync-and-generate
```

This writes to Base44:

- `ScheduleEntry`
- `ScheduleProposal`
- `ComplianceFlag`

## Important warning

Do not call Base44 DELETE endpoints unless you are absolutely sure.
The Base44 API supports deleting multiple records, and an empty query can delete all records in an entity.

## Current algorithm

Version 1 uses a greedy IEP-first scheduler:

1. Pull active students from Base44.
2. Pull active staff from Base44.
3. Rank students by priority:
   - IEP students first
   - More IEP services
   - More required service minutes
   - ENL required minutes
   - MTSS tier 3 / tier 2
4. Schedule IEP service sessions first.
5. Avoid double-booking:
   - student
   - service provider
6. Return service gaps as `ComplianceFlag` records.

## Next improvements

- Add provider availability from `StaffMember.schedule`
- Add room availability
- Schedule ENL minutes explicitly
- Schedule MTSS/Flex groups
- Add normal general education class filling
- Replace greedy scheduling with OR-Tools constraint optimization
