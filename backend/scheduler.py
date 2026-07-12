"""
scheduler.py

IEP / ENL / MTSS-FLEX scheduling engine for CompliWise.

Key design change from earlier versions:
---------------------------------------
Periods are NOT one-size-fits-all across the whole school anymore.
The real bell schedule has 7 periods/day, and FLEX / Lunch-Recess /
Language Block are staggered by grade GROUP so that:

    K/1  -> FLEX, then Lunch/Recess, then Language Block
    2/3  -> FLEX, then Lunch/Recess, then Language Block  (one period later)
    4/5  -> FLEX, then Lunch/Recess, then Language Block  (two periods later)

This stagger is the whole point: it's what keeps FLEX groups (which pull
from a single grade group) from all landing in the same slot school-wide
and colliding with every other group's teachers/rosters at once.

All of this is configurable via PeriodConfig, which is built ONCE before
a scheduling run (e.g. from an admin form or a JSON file) and passed in.
Nothing about period timing is hardcoded as a module-level constant
anymore, other than sane defaults so existing callers don't break.
"""

from typing import Any, Dict, List, Optional, Set, Tuple


DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]


# ---------------------------------------------------------------
# Default period configuration
#
# Real bell schedule (2025-2026 SY):
#   P1  8:10-8:55
#   P2  9:00-9:45
#   P3  9:50-10:35
#   P4  10:40-11:30
#   P5  11:35-12:25
#   P6  12:30-1:20
#   P7  1:25-2:10
#
# Grade groups: K/1, 2/3, 4/5. Each group's FLEX period is the period
# right before that group's Lunch/Recess period, and Language Block
# (core ELA instruction) is the period right after Lunch/Recess.
# ---------------------------------------------------------------

DEFAULT_PERIOD_TIMES = {
    1: "8:10-8:55",
    2: "9:00-9:45",
    3: "9:50-10:35",
    4: "10:40-11:30",
    5: "11:35-12:25",
    6: "12:30-1:20",
    7: "1:25-2:10",
}

# Maps the RAW `grade` value as stored on Student.grade (a plain string
# like "K", "PK", "1", "2" ... "5") to a grade GROUP name. Grade group
# names are used directly ("K/1", "2/3", "4/5") -- no internal shorthand.
DEFAULT_GRADE_GROUPS = {
    "PK": "K/1",
    "K": "K/1",
    "1": "K/1",
    "2": "2/3",
    "3": "2/3",
    "4": "4/5",
    "5": "4/5",
}

DEFAULT_GROUP_PERIODS = {
    "K/1": {"flex": 3, "lunch": 4},
    "2/3": {"flex": 4, "lunch": 5},
    "4/5": {"flex": 5, "lunch": 6},
}

# Fallback subject pattern for periods that are neither FLEX, Lunch/
# Recess, nor Language Block for a given group. This is a placeholder:
# the real master schedule shows these periods (Math, Science, Specials
# rotations, etc.) actually vary by classroom and even by day. Treat
# this as "good enough until we map the full per-group/per-day pattern"
# rather than a source of truth.
GENERAL_ED_PATTERN = {
    1: "Core Instruction",
    2: "Core Instruction",
    3: "Math",
    4: "Math",
    5: "Math",
    6: "Science / Social Studies",
    7: "Specials",
}


class PeriodConfig:
    """
    Everything time/period-related the scheduler needs, editable BEFORE
    a scheduling run instead of hardcoded as module constants. Build one
    of these from admin input (a form, a JSON file, whatever) and pass
    it into schedule_iep_services_first(). Omitting it uses the defaults
    above, so existing callers keep working.
    """

    def __init__(
        self,
        period_times: Optional[Dict[int, str]] = None,
        grade_groups: Optional[Dict[str, str]] = None,
        group_periods: Optional[Dict[str, Dict[str, int]]] = None,
        periods: Optional[List[int]] = None,
        general_ed_pattern: Optional[Dict[int, str]] = None,
    ):
        self.period_times: Dict[int, str] = (
            dict(period_times) if period_times else dict(DEFAULT_PERIOD_TIMES)
        )
        self.grade_groups: Dict[str, str] = (
            dict(grade_groups) if grade_groups else dict(DEFAULT_GRADE_GROUPS)
        )
        self.group_periods: Dict[str, Dict[str, int]] = (
            {group: dict(assignment) for group, assignment in group_periods.items()}
            if group_periods
            else {group: dict(assignment) for group, assignment in DEFAULT_GROUP_PERIODS.items()}
        )
        self.periods: List[int] = (
            list(periods) if periods else sorted(self.period_times.keys())
        )
        self.general_ed_pattern: Dict[int, str] = (
            dict(general_ed_pattern) if general_ed_pattern else dict(GENERAL_ED_PATTERN)
        )
        self._validate()

    def _validate(self):
        """Fail loudly at config time, not silently mid-schedule-run."""
        if not self.group_periods:
            raise ValueError("PeriodConfig needs at least one grade group defined")

        for group, assignment in self.group_periods.items():
            for key in ("flex", "lunch"):
                if key not in assignment:
                    raise ValueError(
                        f"Grade group '{group}' is missing a '{key}' period assignment"
                    )

            flex_p = assignment["flex"]
            lunch_p = assignment["lunch"]

            if len({flex_p, lunch_p}) != 2:
                raise ValueError(
                    f"Grade group '{group}' has overlapping flex/lunch periods: {assignment}"
                )

            for p in (flex_p, lunch_p):
                if p not in self.periods:
                    raise ValueError(
                        f"Grade group '{group}' references period {p}, which "
                        f"isn't in configured periods {self.periods}"
                    )

        referenced_groups = set(self.grade_groups.values())
        missing = referenced_groups - set(self.group_periods.keys())
        if missing:
            raise ValueError(
                f"grade_groups references group(s) {missing} that have no "
                f"entry in group_periods"
            )

    # -----------------------------------------------------------
    # Grade -> group lookups
    # -----------------------------------------------------------

    def get_group_for_grade(self, grade: Any) -> str:
        key = str(grade).strip().upper() if grade is not None else ""
        group = self.grade_groups.get(key)
        if group:
            return group
        # Unrecognized/blank grade: fall back to the first configured
        # group rather than raising, so a bad data row doesn't blow up
        # an entire scheduling run.
        return next(iter(self.group_periods))

    def get_group_for_student(self, student: Dict[str, Any]) -> str:
        return self.get_group_for_grade(student.get("grade"))

    def flex_period(self, student: Dict[str, Any]) -> int:
        return self.group_periods[self.get_group_for_student(student)]["flex"]

    def lunch_period(self, student: Dict[str, Any]) -> int:
        return self.group_periods[self.get_group_for_student(student)]["lunch"]

    def core_periods(self, student: Dict[str, Any]) -> Set[int]:
        """Periods that count as protected core instruction for THIS
        student's group -- everything except that group's own FLEX and
        Lunch/Recess slot. (Language Block counts as core/protected
        too, which is why it's not excluded here.)"""
        assignment = self.group_periods[self.get_group_for_student(student)]
        return set(self.periods) - {assignment["flex"], assignment["lunch"]}

    def subject_for_period(self, student: Dict[str, Any], period: int) -> str:
        """What a student's day looks like at a given period, once
        FLEX/Lunch/Language Block are accounted for."""
        if period == self.flex_period(student):
            return "FLEX"
        if period == self.lunch_period(student):
            return "Lunch/Recess"
        return self.general_ed_pattern.get(period, "Core Instruction")


# ---------------------------------------------------------------
# hard limits on pullouts
# ---------------------------------------------------------------
MAX_PULLOUTS_PER_DAY = 3
MAX_SAME_SERVICE_PER_DAY = 2

MAX_SAME_SERVICE_PER_DAY_OVERRIDES = {
    "ENL": 3,
}


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def max_same_service_per_day(service_type: str) -> int:
    return MAX_SAME_SERVICE_PER_DAY_OVERRIDES.get(
        service_type, MAX_SAME_SERVICE_PER_DAY
    )


MIN_DAYS_BETWEEN_SAME_SERVICE = 0

SERVICE_SESSION_LENGTH_MINUTES = {
    "ENL": 60,
    "SETSS": 45,
    "Speech": 30,
    "OT": 30,
    "PT": 30,
    "Counseling": 30,
    "FLEX": 30,
}
DEFAULT_SESSION_LENGTH_MINUTES = 45


def session_length_for_service(service_type: str) -> int:
    return SERVICE_SESSION_LENGTH_MINUTES.get(
        service_type, DEFAULT_SESSION_LENGTH_MINUTES
    )


MAX_FLEX_GROUP_SIZE = {
    "tier_2": 15,
    "tier_3": 8,
    "enrichment": 10,
}

FLEX_FOCUS_BY_NEED = {
    "reading": "reading",
    "math": "math",
    "writing": "writing",
    "behavior": "behavior",
}

MAX_SERVICE_GROUP_SIZE = {
    "SETSS": 8,
    "ICT": 30,
    "ENL": 25,
    "Speech": 5,
    "OT": 5,
    "PT": 5,
    "Counseling": 8,
    "FLEX": 15,
}

MAX_GEN_ED_CLASS_SIZE = 30


class ScheduleIndex:
    def __init__(self):
        self.student_busy = set()
        self.teacher_busy = set()
        self.class_rosters = {}
        self.student_services_by_day = set()
        self.pullouts_by_student_day = {}
        self.service_count_by_student_day = {}
        self.service_days_by_student = {}
        # For each (teacher, day, period), the set of (subject, room)
        # combos already booked there. This is what lets us tell
        # "joining the same class" apart from "double-booking this
        # teacher into something else."
        self.teacher_slot_subjects = {}

    def student_key(self, student_id, day, period):
        return student_id, day, int(period)

    def teacher_key(self, teacher, day, period):
        return teacher, day, int(period)

    def class_key(self, teacher, day, period, subject, room):
        return teacher or "", day, int(period), subject or "", room or ""

    def is_student_busy(self, student_id, day, period):
        return self.student_key(student_id, day, period) in self.student_busy

    def teacher_period_usage(self, teacher, period):
        """Count how many times this teacher is already scheduled in
        this period, across ALL days this week."""
        if not teacher:
            return 0
        period = int(period)
        return sum(
            1 for (t, d, p) in self.teacher_busy
            if t == teacher and p == period
        )

    def teacher_subjects_at_slot(self, teacher, day, period):
        return self.teacher_slot_subjects.get(
            (teacher, day, int(period)), set()
        )

    def is_teacher_busy(
        self,
        teacher,
        day,
        period,
        subject="",
        room="",
        allow_same_class_group=True,
        max_group_size=None,
    ):
        if not teacher:
            return False

        teacher_key = self.teacher_key(teacher, day, period)

        if teacher_key not in self.teacher_busy:
            return False

        # This is the actual double-booking guard. If the teacher
        # already has a DIFFERENT subject/room booked in this exact
        # slot, they are busy -- full stop, no group-size math applies.
        # Only requests to join the SAME subject/room fall through to
        # the group-size check below.
        existing = self.teacher_subjects_at_slot(teacher, day, period)
        if existing and (subject, room) not in existing:
            return True

        if not allow_same_class_group:
            return True

        class_key = self.class_key(teacher, day, period, subject, room)
        current_size = len(self.class_rosters.get(class_key, set()))

        if max_group_size is None:
            return False

        return current_size + 1 > max_group_size

    def class_group_size(self, teacher, day, period, subject, room):
        key = self.class_key(teacher, day, period, subject, room)
        return len(self.class_rosters.get(key, set()))

    def service_already_on_day(self, student_id, service_type, day):
        return (student_id, service_type, day) in self.student_services_by_day

    def pullouts_already_on_day(self, student_id, day):
        return self.pullouts_by_student_day.get((student_id, day), 0)

    def pullout_limit_reached(self, student_id, day):
        return self.pullouts_already_on_day(student_id, day) >= MAX_PULLOUTS_PER_DAY

    def same_service_limit_reached(self, student_id, service_type, day):
        limit = max_same_service_per_day(service_type)
        if limit <= 0:
            return False
        count = self.service_count_by_student_day.get(
            (student_id, service_type, day), 0
        )
        return count >= limit

    def violates_min_day_gap(self, student_id, service_type, day):
        if MIN_DAYS_BETWEEN_SAME_SERVICE <= 0:
            return False

        scheduled_days = self.service_days_by_student.get((student_id, service_type), set())
        if not scheduled_days:
            return False

        day_idx = DAYS.index(day)
        for other_day in scheduled_days:
            other_idx = DAYS.index(other_day)
            if abs(day_idx - other_idx) < MIN_DAYS_BETWEEN_SAME_SERVICE:
                return True
        return False

    def add_entry(self, entry):
        student_id = entry["student_id"]
        day = entry["day_of_week"]
        period = int(entry["period"])
        teacher = entry.get("teacher", "")
        subject = entry.get("subject", "")
        room = entry.get("room", "")
        service_type = entry.get("service_type", "")
        is_pullout = bool(entry.get("is_pullout"))

        self.student_busy.add(self.student_key(student_id, day, period))

        if teacher:
            self.teacher_busy.add(self.teacher_key(teacher, day, period))

            slot_key = (teacher, day, period)
            if slot_key not in self.teacher_slot_subjects:
                self.teacher_slot_subjects[slot_key] = set()
            self.teacher_slot_subjects[slot_key].add((subject, room))

            class_key = self.class_key(teacher, day, period, subject, room)
            if class_key not in self.class_rosters:
                self.class_rosters[class_key] = set()

            self.class_rosters[class_key].add(student_id)

        if service_type:
            self.student_services_by_day.add((student_id, service_type, day))

            count_key = (student_id, service_type, day)
            self.service_count_by_student_day[count_key] = (
                self.service_count_by_student_day.get(count_key, 0) + 1
            )

            key = (student_id, service_type)
            if key not in self.service_days_by_student:
                self.service_days_by_student[key] = set()
            self.service_days_by_student[key].add(day)

        if is_pullout:
            key = (student_id, day)
            self.pullouts_by_student_day[key] = self.pullouts_by_student_day.get(key, 0) + 1

    def remove_student_entry_at_slot(self, entries, student_id, day, period):
        removed = []
        kept = []
        for entry in entries:
            same_slot = (
                entry.get("student_id") == student_id
                and entry.get("day_of_week") == day
                and int(entry.get("period")) == int(period)
            )
            if same_slot:
                removed.append(entry)
            else:
                kept.append(entry)

        entries[:] = kept
        self.rebuild(entries)

    def rebuild(self, entries):
        self.__init__()
        for entry in entries:
            self.add_entry(entry)


def get_flex_focus_area(student):
    """
    Returns a focus area for FLEX grouping.
    For enrichment students (no MTSS tier), still derive a focus area
    from grade or homeroom so groups are descriptive and spreadable.
    """

    services = student.get("iep_services") or []
    services_text = str(services).lower()

    if "reading" in services_text or "setss" in services_text:
        return "reading"
    if "math" in services_text:
        return "math"
    if "writing" in services_text:
        return "writing"
    if "behavior" in services_text or "counseling" in services_text:
        return "behavior"

    grade = str(student.get("grade") or "").strip()
    if grade:
        return f"grade_{grade}"

    homeroom = str(student.get("homeroom") or "").strip()
    if homeroom:
        return homeroom

    return "general"


def get_teacher_grade_group(staff: Dict[str, Any], period_config: PeriodConfig) -> Optional[str]:
    """
    Infers a gen-ed teacher's OWN homeroom grade group from their
    `grade` field, so build_flex_groups can tell whether borrowing them
    for a different grade group's FLEX slot would pull them off their
    own class's core instruction.
    """
    grade = staff.get("grade")
    if grade is None or str(grade).strip() == "":
        return None
    return period_config.get_group_for_grade(grade)


def teacher_has_core_conflict(staff: Dict[str, Any], period: int, period_config: PeriodConfig) -> bool:
    """
    True if `period` is protected core-instruction time for this
    teacher's OWN grade group (i.e. neither their own FLEX period nor
    their own lunch period). A teacher can only be borrowed for another
    grade group's FLEX slot at periods where their own class doesn't
    need them -- their own FLEX period (their kids are elsewhere too)
    or their own lunch period.
    """
    home_group = get_teacher_grade_group(staff, period_config)
    if home_group is None or home_group not in period_config.group_periods:
        return False
    assignment = period_config.group_periods[home_group]
    return period not in (assignment["flex"], assignment["lunch"])


def pick_flex_teacher(focus_area: str, staff_members: list, load_fn=None, exclude: set = None) -> str:
    exclude = exclude or set()

    def load(name):
        if load_fn is None:
            return 0
        return load_fn(name)

    def best(candidates):
        candidates = [c for c in candidates if c not in exclude]   # never reuse a teacher already at this period
        if not candidates:
            return ""
        return min(candidates, key=load)

    enl_certified = [
        staff_full_name(s) for s in staff_members
        if s.get("is_certified_enl") and staff_full_name(s)
    ]
    setss_qualified = [
        staff_full_name(s) for s in staff_members
        if (s.get("can_deliver_setss") or s.get("is_certified_sped"))
        and staff_full_name(s)
    ]
    gen_ed = [
        staff_full_name(s) for s in staff_members
        if s.get("title") == "General Education Teacher" and staff_full_name(s)
    ]
    counselors = [
        staff_full_name(s) for s in staff_members
        if s.get("title") in ("School Counselor", "School Psychologist", "Social Worker")
        and staff_full_name(s)
    ]
    ict = [
        staff_full_name(s) for s in staff_members
        if s.get("title") == "ICT Co-Teacher" and staff_full_name(s)
    ]
    # Paraprofessionals don't carry their own homeroom class, so they
    # never compete with a grade-level teacher's core instruction for
    # the same period -- they're the natural default staffing pool for
    # FLEX groups, and are checked BEFORE gen-ed teachers below.
    paraprofessionals = [
        staff_full_name(s) for s in staff_members
        if s.get("title") == "Paraprofessional" and staff_full_name(s)
    ]
    all_instructional = list({
        staff_full_name(s) for s in staff_members
        if s.get("title") not in ("Principal", "Assistant Principal")
        and staff_full_name(s)
    })

    if focus_area in ("reading", "writing"):
        return (
            best(setss_qualified)
            or best(paraprofessionals)
            or best(gen_ed)
            or best(ict)
            or best(all_instructional)
        )
    if focus_area == "math":
        return (
            best(paraprofessionals)
            or best(gen_ed)
            or best(setss_qualified)
            or best(ict)
            or best(all_instructional)
        )
    if focus_area == "behavior":
        return best(counselors) or best(paraprofessionals) or best(all_instructional)

    return (
        best(paraprofessionals)
        or best(gen_ed)
        or best(ict)
        or best(all_instructional)
    )


def build_flex_groups(students, staff_members, period_config: PeriodConfig, schedule_index=None):
    """
    Buckets students into FLEX groups keyed by (grade GROUP, tier,
    focus_area) -- grade group is part of the key so a "reading tier_2"
    bucket never mixes, say, K/1 kids with 4/5 kids into one group at
    one period. Each group's period comes from period_config, staggered
    by grade group so FLEX groups across the school don't all collide
    in the same slot.
    """
    groups = []
    buckets = {}
    flex_load = {}
    used_teachers_by_period = {}

    def load_fn(name):
        return flex_load.get(name, 0)

    for student in students:
        student_id = student.get("student_id")
        if not student_id:
            continue

        # ENL is scheduled independently through ENL services.
        # It should never create a FLEX group.
        if student.get("enl_minutes_required", 0) > 0 and not student.get("mtss_tier"):
            continue

        grade_group = period_config.get_group_for_student(student)
        mtss_tier = student.get("mtss_tier")
        focus_area = get_flex_focus_area(student)

        if mtss_tier not in ["tier_2", "tier_3"]:
            bucket_key = (grade_group, "enrichment", focus_area)
        else:
            bucket_key = (grade_group, mtss_tier, focus_area)

        buckets.setdefault(bucket_key, []).append(student)

    for (grade_group, tier, focus_area), bucket_students in buckets.items():
        if tier == "enrichment":
            max_size = MAX_FLEX_GROUP_SIZE["enrichment"]
            base_name = f"FLEX Enrichment ({grade_group}) - {focus_area}"
            mtss_tier = "tier_2"
        else:
            max_size = MAX_FLEX_GROUP_SIZE.get(tier, 10)
            base_name = f"FLEX {tier.upper()} ({grade_group}) - {focus_area}"
            mtss_tier = tier

        flex_period = period_config.group_periods[grade_group]["flex"]
        already_used = used_teachers_by_period.setdefault(flex_period, set())

        # Any gen-ed teacher whose OWN grade group has this period as
        # protected core-instruction time is off-limits for THIS
        # grade group's FLEX -- borrowing them would mean abandoning
        # their own class mid-lesson. This is separate from
        # already_used (which only prevents FLEX-vs-FLEX collisions
        # within the same period) and is recomputed per bucket since
        # it depends only on the period, not on prior picks.
        core_conflicted = {
            staff_full_name(s) for s in staff_members
            if staff_full_name(s) and teacher_has_core_conflict(s, flex_period, period_config)
        }

        for i in range(0, len(bucket_students), max_size):
            chunk = bucket_students[i:i + max_size]
            group_number = (i // max_size) + 1

            # Recomputed each iteration (not hoisted) since already_used
            # keeps growing as chunks within THIS bucket get teachers
            # assigned -- a frozen union taken before the loop would miss
            # picks made by earlier chunks of the same bucket.
            teacher = pick_flex_teacher(
                focus_area, staff_members, load_fn=load_fn,
                exclude=already_used | core_conflicted
            )
            if not teacher:
                continue

            already_used.add(teacher)
            flex_load[teacher] = flex_load.get(teacher, 0) + 1

            for day in DAYS:
                groups.append({
                    "name": f"{base_name} Group {group_number}",
                    "tier": mtss_tier,
                    "grade_group": grade_group,
                    "focus_area": focus_area,
                    "teacher": teacher,
                    "student_ids": [s["student_id"] for s in chunk],
                    "max_group_size": max_size,
                    "day_of_week": day,
                    "period": flex_period,
                    "status": "active",
                    "group_number": group_number,
                })

    return groups


def validate_class_sizes(entries):
    flags = []
    class_rosters = {}

    for entry in entries:
        if entry.get("is_pullout"):
            continue
        if entry.get("service_type") != "general_ed":
            continue
        if entry.get("subject") in ("FLEX", "Lunch/Recess"):
            continue
        key = (
            entry.get("teacher", ""),
            entry.get("day_of_week"),
            int(entry.get("period")),
            entry.get("subject", ""),
            entry.get("room", "")
        )

        if key not in class_rosters:
            class_rosters[key] = set()

        class_rosters[key].add(entry["student_id"])

    for key, student_ids in class_rosters.items():
        teacher, day, period, subject, room = key
        class_size = len(student_ids)

        if class_size > MAX_GEN_ED_CLASS_SIZE:
            flags.append({
                "student_id": "multiple",
                "flag_type": "group_size_violation",
                "severity": "warning",
                "title": f"{subject} class exceeds max size",
                "description": (
                    f"{teacher}'s {subject} class on {day}, period {period} "
                    f"has {class_size} students. Max allowed is {MAX_GEN_ED_CLASS_SIZE}."
                ),
                "legal_reference": "School scheduling constraint",
                "affected_period": f"{day} period {period}",
                "status": "open"
            })

    return flags


def class_group_size(
    entries: List[Dict[str, Any]],
    teacher: str,
    day: str,
    period: int,
    subject: str,
    room: str
) -> int:
    count = 0

    for entry in entries:
        if entry.get("teacher") != teacher:
            continue
        if entry.get("day_of_week") != day:
            continue
        if int(entry.get("period")) != int(period):
            continue
        if entry.get("subject") != subject:
            continue
        if entry.get("room", "") != room:
            continue
        count += 1

    return count


def score_slot_for_service(
    period: int,
    service_type: str,
    student: Dict[str, Any],
    period_config: PeriodConfig,
) -> int:
    service_type = service_type.lower()
    lunch_period = period_config.lunch_period(student)
    flex_period = period_config.flex_period(student)

    if period == lunch_period:
        return -10000

    if period == flex_period:
        return 1000

    if service_type == "enl" and period in {1, 2}:
        return 300

    if period in period_config.core_periods(student):
        return -1000

    return 0


def dedupe_flex_groups(flex_groups):
    """
    Collapse truly duplicate FLEX group records (same grade_group + tier
    + focus_area + teacher + day + period + group_number) into one group
    per slot.

    IMPORTANT: group_number (and grade_group) are part of the merge key.
    Group 1 and Group 2 of the same bucket represent DIFFERENT sets of
    students that didn't fit in one roster together -- they must stay
    separate records, or you get exactly the "20 students, max 10" bug
    (two 10-student chunks silently recombined into one 20-student
    group). Only records that are true re-emissions of the SAME chunk
    (e.g. from a duplicate build_flex_groups call) should merge.
    """
    import re

    merged: dict = {}
    overflow: dict = {}

    for group in flex_groups:
        base_key = (
            group.get("grade_group"),
            group.get("tier"),
            group.get("focus_area"),
            group.get("teacher"),
            group.get("day_of_week"),
            int(group.get("period")),
            group.get("group_number"),  # keeps distinct chunks separate
        )

        if base_key not in merged:
            merged[base_key] = {
                **group,
                "student_ids": list(group.get("student_ids", []))
            }
            continue

        existing = merged[base_key]
        existing_ids = set(existing["student_ids"])
        max_size = existing.get("max_group_size")
        overflow_queue = overflow.setdefault(base_key, [])

        for student_id in group.get("student_ids", []):
            if student_id in existing_ids:
                continue

            if max_size is None or len(existing["student_ids"]) < max_size:
                existing["student_ids"].append(student_id)
                existing_ids.add(student_id)
            else:
                overflow_queue.append(student_id)

    result = list(merged.values())

    for base_key, student_ids in overflow.items():
        prototype = merged[base_key]
        max_size = prototype.get("max_group_size") or 10
        base_name_clean = re.sub(r" Group \d+$", "", prototype.get("name", "FLEX Group"))

        group_number = (prototype.get("group_number") or 1) + 1
        for i in range(0, len(student_ids), max_size):
            chunk = student_ids[i: i + max_size]
            result.append({
                **prototype,
                "name": f"{base_name_clean} Group {group_number}",
                "student_ids": chunk,
                "group_number": group_number,
            })
            group_number += 1

    return result


def full_student_name(student: Dict[str, Any]) -> str:
    first = student.get("first_name", "")
    last = student.get("last_name", "")
    return f"{first} {last}".strip() or student.get("student_id", "Unknown Student")


def priority_score(student: Dict[str, Any]) -> int:
    score = 0

    if student.get("has_iep"):
        score += 10000

    score += len(student.get("iep_services") or []) * 500

    enl_minutes = int(student.get("enl_minutes_required") or 0)
    score += enl_minutes

    mtss_tier = student.get("mtss_tier")

    if mtss_tier == "tier_3":
        score += 2000
    elif mtss_tier == "tier_2":
        score += 1000

    return score


def staff_full_name(staff: Dict[str, Any]) -> str:
    return f"{staff.get('first_name', '')} {staff.get('last_name', '')}".strip()


def is_general_ed_teacher(staff: Dict[str, Any]) -> bool:
    return staff.get("title") == "General Education Teacher"


def get_general_ed_teachers(staff_members: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [staff for staff in staff_members if is_general_ed_teacher(staff)]


def pick_gen_ed_teacher_for_student(
    student,
    subject,
    staff_members,
    day="",
    period=0,
    existing_entries=None,
    schedule_index=None,
):
    """
    Returns a gen-ed teacher for this student's class at this specific
    day/period, preferring (in order) the student's homeroom teacher,
    then any teacher matched to their grade, then any remaining gen-ed
    teacher -- but SKIPPING anyone already busy at that exact slot when
    a schedule_index is supplied. Only returns "" when literally no
    gen-ed teacher is free at that slot, so callers can trust that a
    non-empty result is actually usable instead of discovering the
    conflict themselves afterward.
    """
    homeroom = student.get("homeroom")
    grade = str(student.get("grade", "")).lower()
    room = homeroom or ""

    gen_ed_teachers = [
        staff for staff in staff_members
        if staff.get("title") == "General Education Teacher"
    ]

    if not gen_ed_teachers:
        return ""

    homeroom_matches = []
    grade_matches = []
    everyone_else = []

    for teacher in gen_ed_teachers:
        name = staff_full_name(teacher)
        if not name:
            continue

        teacher_room = teacher.get("room") or teacher.get("homeroom") or ""
        if homeroom and teacher_room == homeroom:
            homeroom_matches.append(name)
            continue

        searchable = " ".join([
            str(teacher.get("grade") or ""),
            str(teacher.get("homeroom") or ""),
            str(teacher.get("room") or ""),
        ]).lower()
        if grade and grade in searchable:
            grade_matches.append(name)
            continue

        everyone_else.append(name)

    ordered_candidates = homeroom_matches + grade_matches + everyone_else

    if schedule_index is None:
        # No availability info to check against -- preserve old behavior.
        return ordered_candidates[0] if ordered_candidates else ""

    for name in ordered_candidates:
        if schedule_index.is_teacher_busy(
            teacher=name,
            day=day,
            period=period,
            subject=subject,
            room=room,
            allow_same_class_group=True,
            max_group_size=MAX_GEN_ED_CLASS_SIZE,
        ):
            continue
        return name

    # Genuinely nobody available at this slot -- this is a real gap,
    # not something a fallback can paper over.
    return ""


def get_student_services(student: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Mandated, individually-scheduled services only.

    NOTE: FLEX for MTSS tier_2/tier_3 students is intentionally NOT
    generated here. It's handled entirely by build_flex_groups() /
    apply_flex_groups_to_schedule(), which produces a capped-roster,
    properly-staffed group placement. A duplicate "FLEX TIER_x" entry
    used to be appended here too, but pick_teacher_for_service() has no
    branch that matches service_type "flex", so it always came back
    teacherless -- producing a second, broken, unstaffed FLEX booking
    for every MTSS student on top of their real group. Do not re-add
    a FLEX block here.
    """
    services = []

    if student.get("has_iep"):
        raw_services = student.get("iep_services") or []

        if raw_services:
            for service in raw_services:
                if isinstance(service, dict):
                    service_type = (
                        service.get("service_type")
                        or service.get("type")
                        or service.get("name")
                        or "SETSS"
                    )
                    minutes = int(
                        service.get("minutes_per_week")
                        or service.get("minutes")
                        or service.get("required_minutes")
                        or 30
                    )
                else:
                    service_type = str(service)
                    minutes = 30

                services.append({
                    "subject": service_type,
                    "service_type": service_type,
                    "minutes": minutes,
                    "is_pullout": False
                })
        else:
            services.append({
                "subject": "IEP Support",
                "service_type": "SETSS",
                "minutes": 30,
                "is_pullout": True
            })

    # ENL is a mandated, individually-scheduled pullout service and
    # must remain here regardless of anything done to the FLEX block
    # above -- this is separate from MTSS FLEX and was accidentally
    # removed alongside it in a previous edit. Restored.
    enl_minutes = int(student.get("enl_minutes_required") or 0)
    if enl_minutes > 0:
        services.append({
            "subject": "ENL",
            "service_type": "ENL",
            "minutes": enl_minutes,
            "is_pullout": True
        })

    return services


def find_open_slot_fast(
    index: ScheduleIndex,
    student: Dict[str, Any],
    period_config: PeriodConfig,
    teacher="",
    subject="",
    service_type="",
    is_pullout=False
):
    """
    Takes `student` (not just student_id) now, since period scoring is
    grade-group-dependent. `subject` stays a separate parameter from
    service_type -- rosters are keyed by the entry's actual `subject`
    field, which differs from service_type for fallback SETSS
    ("IEP Support" vs "SETSS") and FLEX-via-MTSS ("FLEX TIER_2" vs
    "FLEX"). Passing service_type into the roster check instead of the
    real subject makes group-size caps silently no-op and lets a
    teacher get booked into two different subjects in the same slot.
    """
    student_id = student.get("student_id")
    core_periods = period_config.core_periods(student)
    candidate_slots = []

    for day in DAYS:

        if is_pullout:
            if index.pullout_limit_reached(student_id, day):
                continue
            if index.same_service_limit_reached(student_id, service_type, day):
                continue
            if index.violates_min_day_gap(student_id, service_type, day):
                continue

        for period in period_config.periods:
            if index.is_student_busy(student_id, day, period):
                continue

            if index.is_teacher_busy(
                teacher=teacher,
                day=day,
                period=period,
                subject=subject,
                room="",
                allow_same_class_group=True,
                max_group_size=MAX_SERVICE_GROUP_SIZE.get(service_type)
            ):
                continue

            score = score_slot_for_service(period, service_type, student, period_config)

            if is_pullout and period in core_periods and service_type.lower() != "enl":
                score -= 1000

            if index.service_already_on_day(student_id, service_type, day):
                score -= 300

            if index.pullouts_already_on_day(student_id, day) > 0:
                score -= 200

            if is_pullout and service_type.lower() != "flex":
                usage = index.teacher_period_usage(teacher, period)
                score -= 150 * usage

            candidate_slots.append({
                "day": day,
                "period": period,
                "score": score
            })

    if not candidate_slots:
        return None

    candidate_slots.sort(key=lambda slot: slot["score"], reverse=True)
    best = candidate_slots[0]

    if best["score"] <= -10000:
        return None

    return best["day"], best["period"]


def pick_teacher_for_service(
    service_type: str,
    staff_members: List[Dict[str, Any]],
    load_fn=None
) -> str:
    service_lower = service_type.lower()

    def load(name):
        if load_fn is None:
            return 0
        return load_fn(name)

    candidates = []

    for staff in staff_members:
        title = (staff.get("title") or "").lower()
        name = f"{staff.get('first_name', '')} {staff.get('last_name', '')}".strip()

        if not name:
            continue

        if service_lower == "speech" and staff.get("is_certified_slp"):
            candidates.append(name)
        elif service_lower in ["setss", "iep support"] and staff.get("can_deliver_setss"):
            candidates.append(name)
        elif service_lower == "enl" and staff.get("is_certified_enl"):
            candidates.append(name)
        elif service_lower == "counseling" and (
            "counselor" in title or "psychologist" in title or "social worker" in title
        ):
            candidates.append(name)

    if not candidates:
        return ""

    return min(candidates, key=load)


def validate_staff_schedule(staff_schedule):
    flags = []

    for teacher, days in staff_schedule.items():
        for day, periods in days.items():
            for period, blocks in periods.items():
                for block in blocks:
                    students = block["students"]
                    count = len(students)

                    if block["service_type"] == "general_ed":
                        max_size = MAX_GEN_ED_CLASS_SIZE
                    else:
                        max_size = MAX_SERVICE_GROUP_SIZE.get(block["service_type"], 8)

                    if count > max_size:
                        flags.append({
                            "student_id": "multiple",
                            "flag_type": "group_size_violation",
                            "severity": "warning",
                            "title": f"{teacher} has too many students",
                            "description": (
                                f"{teacher} has {count} students for "
                                f"{block['subject']} on {day}, period {period}. "
                                f"Max allowed is {max_size}."
                            ),
                            "legal_reference": "School scheduling constraint",
                            "affected_period": f"{day} period {period}",
                            "status": "open"
                        })

    return flags


def validate_pullout_limits(entries, students_by_id):
    flags = []

    pullouts_by_student_day = {}
    service_by_student_day = {}

    for entry in entries:
        if not entry.get("is_pullout"):
            continue

        student_id = entry["student_id"]
        day = entry["day_of_week"]
        service_type = entry.get("service_type", "")

        key = (student_id, day)
        pullouts_by_student_day[key] = pullouts_by_student_day.get(key, 0) + 1

        svc_key = (student_id, day, service_type)
        service_by_student_day[svc_key] = service_by_student_day.get(svc_key, 0) + 1

    for (student_id, day), count in pullouts_by_student_day.items():
        if count > MAX_PULLOUTS_PER_DAY:
            student = students_by_id.get(student_id, {})
            student_name = full_student_name(student)

            flags.append({
                "student_id": student_id,
                "flag_type": "excessive_pullouts",
                "severity": "warning",
                "title": f"{student_name} has too many pullouts on {day}",
                "description": (
                    f"{student_name} has {count} pullout services on {day}. "
                    f"Max recommended is {MAX_PULLOUTS_PER_DAY} per day."
                ),
                "legal_reference": "Least Restrictive Environment (LRE) consideration",
                "affected_period": f"{day} (all periods)",
                "status": "open"
            })

    for (student_id, day, service_type), count in service_by_student_day.items():
        limit = max_same_service_per_day(service_type)
        if count > limit:
            student = students_by_id.get(student_id, {})
            student_name = full_student_name(student)

            flags.append({
                "student_id": student_id,
                "flag_type": "duplicate_service_same_day",
                "severity": "warning",
                "title": f"{student_name} has duplicate {service_type} on {day}",
                "description": (
                    f"{student_name} is scheduled for {service_type} {count} times "
                    f"on {day}. Max allowed is {limit} per day."
                ),
                "legal_reference": "School scheduling constraint",
                "affected_period": f"{day} (all periods)",
                "status": "open"
            })

    return flags


def apply_flex_groups_to_schedule(all_entries, flex_groups, students_by_id, schedule_index):
    """
    Guards against a teacher being double-booked into two DIFFERENT
    FLEX groups at the same day/period (e.g. pick_flex_teacher assigning
    the same teacher to both a "reading" bucket and a "math" bucket
    that land in the same slot for the same grade group). Joining the
    SAME group is still fine and expected -- only a genuine conflicting
    subject gets skipped, with a compliance flag raised so it's visible
    rather than silently dropped.
    """
    conflict_flags = []

    for group in flex_groups:
        day = group["day_of_week"]
        period = int(group["period"])
        teacher = group.get("teacher", "")
        subject = group["name"]

        if teacher and schedule_index.is_teacher_busy(
            teacher=teacher,
            day=day,
            period=period,
            subject=subject,
            room="",
            allow_same_class_group=True,
            max_group_size=group.get("max_group_size"),
        ):
            conflict_flags.append({
                "student_id": "multiple",
                "flag_type": "teacher_double_booked",
                "severity": "critical",
                "title": f"{teacher} double-booked for FLEX",
                "description": (
                    f"{teacher} is already scheduled for a different class "
                    f"on {day}, period {period}, so '{subject}' could not "
                    f"be placed there. Reassign a teacher for this group."
                ),
                "legal_reference": "School scheduling constraint",
                "affected_period": f"{day} period {period}",
                "status": "open"
            })
            continue

        for student_id in group.get("student_ids", []):
            if schedule_index.is_student_busy(student_id, day, period):
                continue

            entry = {
                "student_id": student_id,
                "day_of_week": day,
                "period": period,
                "subject": subject,
                "teacher": teacher,
                "room": "",
                "is_pullout": False,
                "service_type": "FLEX",
                "is_flex_period": True
            }

            all_entries.append(entry)
            schedule_index.add_entry(entry)

    return conflict_flags


def remove_student_entry_at_slot(entries, student_id, day, period):
    entries[:] = [
        entry for entry in entries
        if not (
            entry.get("student_id") == student_id
            and entry.get("day_of_week") == day
            and int(entry.get("period")) == int(period)
        )
    ]


def add_to_staff_schedule(
    staff_schedule,
    teacher,
    day,
    period,
    student_id,
    student_name,
    subject,
    service_type,
    is_pullout
):
    if not teacher:
        return

    if teacher not in staff_schedule:
        staff_schedule[teacher] = {}

    if day not in staff_schedule[teacher]:
        staff_schedule[teacher][day] = {}

    if period not in staff_schedule[teacher][day]:
        staff_schedule[teacher][day][period] = []

    blocks = staff_schedule[teacher][day][period]

    block = None
    for existing_block in blocks:
        if existing_block["subject"] == subject and existing_block["service_type"] == service_type:
            block = existing_block
            break

    if block is None:
        block = {
            "subject": subject,
            "service_type": service_type,
            "is_pullout": is_pullout,
            "students": []
        }
        blocks.append(block)

    block["students"].append({
        "student_id": student_id,
        "student_name": student_name
    })


def core_subject_for_period(period: int, student: Dict[str, Any], period_config: PeriodConfig) -> str:
    return period_config.subject_for_period(student, period)


def pullouts_already_on_day(
    entries: List[Dict[str, Any]],
    student_id: str,
    day: str
) -> int:
    count = 0
    for entry in entries:
        if (
            entry["student_id"] == student_id
            and entry["day_of_week"] == day
            and entry.get("is_pullout")
        ):
            count += 1
    return count


def service_already_on_day(
    entries: List[Dict[str, Any]],
    student_id: str,
    service_type: str,
    day: str
) -> bool:
    for entry in entries:
        if (
            entry["student_id"] == student_id
            and entry["day_of_week"] == day
            and entry.get("service_type") == service_type
        ):
            return True
    return False


def schedule_iep_services_first(
    students: List[Dict[str, Any]],
    staff_members: List[Dict[str, Any]] | None = None,
    school_year: str = "2026-2027",
    period_config: Optional[PeriodConfig] = None,
) -> Dict[str, Any]:
    """
    Main scheduler.

    Hard limits enforced:
    - MAX_PULLOUTS_PER_DAY
    - MAX_SAME_SERVICE_PER_DAY (with per-service overrides)
    - MIN_DAYS_BETWEEN_SAME_SERVICE
    - Teachers can never be double-booked into two different
      subjects/groups in the same day/period slot.
    - Service and FLEX group rosters are capped at
      MAX_SERVICE_GROUP_SIZE / MAX_FLEX_GROUP_SIZE.
    - FLEX / Lunch-Recess / Language Block periods are staggered by
      grade group (K/1, 2/3, 4/5) via period_config, so FLEX groups
      across the whole school don't collide in one slot.
    """

    staff_members = staff_members or []
    period_config = period_config or PeriodConfig()

    all_entries: List[Dict[str, Any]] = []
    schedule_index = ScheduleIndex()
    schedule_proposals: List[Dict[str, Any]] = []
    compliance_flags: List[Dict[str, Any]] = []
    staff_schedule: Dict[str, Any] = {}

    ranked_students = sorted(students, key=priority_score, reverse=True)

    students_by_id = {
        student["student_id"]: student
        for student in students
        if student.get("student_id")
    }

    service_teacher_load: Dict[str, int] = {}

    def service_teacher_load_fn(name):
        return service_teacher_load.get(name, 0)

    # ---------------------------------------------------------
    # 2. Build and place FLEX groups FIRST.
    #
    # FLEX groups are rigid -- same teacher, same slot, every day, all
    # week -- and now that slot is grade-group-specific via
    # period_config. Pullout sessions are flexible -- find_open_slot_fast
    # can place them in whatever periods are left for that student's
    # grade group. By locking in FLEX commitments first, a teacher
    # who's already leading a FLEX group becomes correctly "busy" by
    # the time pullout scheduling runs, so find_open_slot_fast naturally
    # routes those pullouts elsewhere instead of colliding with FLEX.
    # ---------------------------------------------------------
    flex_groups = build_flex_groups(
        students=ranked_students,
        staff_members=staff_members,
        period_config=period_config,
        schedule_index=schedule_index
    )

    flex_groups = dedupe_flex_groups(flex_groups)

    student_flex_group_rows = []

    for group in flex_groups:
        for student_id in group["student_ids"]:
            student_flex_group_rows.append({
                "student_id": student_id,
                "group_name": group["name"],
                "tier": group["tier"],
                "grade_group": group["grade_group"],
                "focus_area": group["focus_area"],
                "teacher": group["teacher"],
                "day_of_week": group["day_of_week"],
                "period": group["period"],
            })

    flex_conflict_flags = apply_flex_groups_to_schedule(
        all_entries=all_entries,
        flex_groups=flex_groups,
        students_by_id=students_by_id,
        schedule_index=schedule_index
    )
    compliance_flags.extend(flex_conflict_flags)

    for group in flex_groups:
        teacher = group.get("teacher", "")
        day = group.get("day_of_week")
        period = group.get("period")
        subject = group.get("name", "FLEX Group")
        service_type = "FLEX"

        for student_id in group.get("student_ids", []):
            student = students_by_id.get(student_id, {})
            student_name = full_student_name(student)

            add_to_staff_schedule(
                staff_schedule=staff_schedule,
                teacher=teacher,
                day=day,
                period=period,
                student_id=student_id,
                student_name=student_name,
                subject=subject,
                service_type=service_type,
                is_pullout=False
            )

    # ---------------------------------------------------------
    # 3. Schedule required (mandated) services
    # ---------------------------------------------------------
    for student in ranked_students:
        student_id = student.get("student_id")
        student_name = full_student_name(student)

        if not student_id:
            continue

        services = get_student_services(student)

        for service in services:
            service_type = service["service_type"]
            subject = service["subject"]
            minutes = service["minutes"]
            is_pullout = service["is_pullout"]

            session_length = session_length_for_service(service_type)
            sessions_needed = max(1, round(minutes / session_length))
            teacher = pick_teacher_for_service(
                service_type, staff_members, load_fn=service_teacher_load_fn
            )

            no_qualified_staff = not teacher
            scheduled_sessions = 0

            for _ in range(sessions_needed):
                slot = find_open_slot_fast(
                    index=schedule_index,
                    student=student,
                    period_config=period_config,
                    teacher=teacher,
                    subject=subject,
                    service_type=service_type,
                    is_pullout=is_pullout
                )

                if slot is None:
                    break

                day, period = slot

                entry = {
                    "student_id": student_id,
                    "day_of_week": day,
                    "period": period,
                    "subject": subject,
                    "teacher": teacher,
                    "room": "",
                    "is_pullout": is_pullout,
                    "service_type": service_type,
                    "is_flex_period": period == period_config.flex_period(student)
                }
                if is_pullout:
                    schedule_index.remove_student_entry_at_slot(
                        entries=all_entries,
                        student_id=student_id,
                        day=day,
                        period=period
                    )
                all_entries.append(entry)
                schedule_index.add_entry(entry)

                add_to_staff_schedule(
                    staff_schedule=staff_schedule,
                    teacher=teacher,
                    day=day,
                    period=period,
                    student_id=student_id,
                    student_name=student_name,
                    subject=subject,
                    service_type=service_type,
                    is_pullout=is_pullout
                )

                scheduled_sessions += 1

            if teacher and scheduled_sessions:
                service_teacher_load[teacher] = (
                    service_teacher_load.get(teacher, 0) + scheduled_sessions
                )

            if scheduled_sessions < sessions_needed:
                if no_qualified_staff:
                    reason_hint = (
                        f" No staff member matching {service_type} was found. "
                        f"This is a staffing gap, not a pullout-limit issue -- "
                        f"add or designate a qualified provider for {service_type}."
                    )
                elif is_pullout:
                    same_service_limit = max_same_service_per_day(service_type)
                    reason_hint = (
                        f" This may be due to the daily pullout limit "
                        f"(max {MAX_PULLOUTS_PER_DAY}/day), same-service "
                        f"limit (max {same_service_limit}/day for {service_type}), "
                        f"or the assigned provider's schedule being full -- "
                        f"leaving no compliant slot."
                    )
                else:
                    reason_hint = ""

                compliance_flags.append({
                    "student_id": student_id,
                    "flag_type": "iep_violation",
                    "severity": "critical",
                    "title": f"Could not fully schedule {service_type}",
                    "description": (
                        f"{student_name} needed {sessions_needed} sessions of "
                        f"{service_type}, but only {scheduled_sessions} were scheduled."
                        f"{reason_hint}"
                    ),
                    "legal_reference": "Mandated service requirement",
                    "affected_period": "weekly schedule",
                    "status": "open"
                })

    # ---------------------------------------------------------
    # 4. Fill remaining periods: FLEX / Lunch-Recess / Language Block
    #    / general-ed, all resolved per-student via period_config.
    #
    # Every branch here goes through the real teacher-busy check before
    # booking, and pick_gen_ed_teacher_for_student is now given the
    # schedule_index so it can try OTHER gen-ed teachers before giving
    # up on a period entirely, instead of hard-failing the moment its
    # single preferred teacher happens to be busy.
    # ---------------------------------------------------------
    for student in ranked_students:
        student_id = student.get("student_id")
        student_name = full_student_name(student)

        if not student_id:
            continue

        flex_period = period_config.flex_period(student)
        lunch_period = period_config.lunch_period(student)

        for day in DAYS:
            for period in period_config.periods:
                if schedule_index.is_student_busy(student_id, day, period):
                    continue

                if period == flex_period:
                    subject = "FLEX"
                    room = student.get("homeroom") or ""
                    teacher = pick_gen_ed_teacher_for_student(
                        student=student,
                        subject=subject,
                        staff_members=staff_members,
                        day=day,
                        period=period,
                        existing_entries=all_entries,
                        schedule_index=schedule_index,
                    )

                    if not teacher:
                        compliance_flags.append({
                            "student_id": student_id,
                            "flag_type": "unscheduled_flex_period",
                            "severity": "warning",
                            "title": f"{student_name} has no FLEX placement on {day}",
                            "description": (
                                f"{student_name}'s FLEX group placement on {day} "
                                f"period {period} was skipped (teacher conflict or "
                                f"group full), and no fallback gen-ed teacher was "
                                f"available at that slot either. Manually assign "
                                f"this student a FLEX group or provider for {day}."
                            ),
                            "legal_reference": "MTSS / FLEX support requirement",
                            "affected_period": f"{day} period {period}",
                            "status": "open"
                        })
                        continue

                    entry = {
                        "student_id": student_id,
                        "day_of_week": day,
                        "period": period,
                        "subject": subject,
                        "teacher": teacher,
                        "room": room,
                        "is_pullout": False,
                        "service_type": "FLEX",
                        "is_flex_period": True
                    }

                elif period == lunch_period:
                    entry = {
                        "student_id": student_id,
                        "day_of_week": day,
                        "period": period,
                        "subject": "Lunch/Recess",
                        "teacher": "",
                        "room": "",
                        "is_pullout": False,
                        "service_type": "general_ed",
                        "is_flex_period": False
                    }

                else:
                    subject = period_config.general_ed_pattern.get( period, "Core Instruction")
                    room = student.get("homeroom") or ""

                    teacher = pick_gen_ed_teacher_for_student(
                        student=student,
                        subject=subject,
                        staff_members=staff_members,
                        day=day,
                        period=period,
                        existing_entries=all_entries,
                        schedule_index=schedule_index,
                    )

                    if not teacher:
                        compliance_flags.append({
                            "student_id": student_id,
                            "flag_type": "teacher_double_booked",
                            "severity": "critical",
                            "title": f"No gen-ed teacher available during {subject}",
                            "description": (
                                f"Every gen-ed teacher eligible for {student_name}'s "
                                f"{subject} on {day}, period {period} is already "
                                f"committed to a different class/service at that "
                                f"exact slot (likely an IEP/ENL/related-service "
                                f"pullout or FLEX group for another student). "
                                f"Assign a covering teacher, or move the "
                                f"conflicting service to another slot."
                            ),
                            "legal_reference": "School scheduling constraint",
                            "affected_period": f"{day} period {period}",
                            "status": "open"
                        })
                        continue

                    entry = {
                        "student_id": student_id,
                        "day_of_week": day,
                        "period": period,
                        "subject": subject,
                        "teacher": teacher,
                        "room": room,
                        "is_pullout": False,
                        "service_type": "general_ed",
                        "is_flex_period": False
                    }

                all_entries.append(entry)
                schedule_index.add_entry(entry)

                add_to_staff_schedule(
                    staff_schedule=staff_schedule,
                    teacher=entry["teacher"],
                    day=day,
                    period=period,
                    student_id=student_id,
                    student_name=student_name,
                    subject=entry["subject"],
                    service_type=entry["service_type"],
                    is_pullout=False
                )

    # ---------------------------------------------------------
    # 5. Validate
    # ---------------------------------------------------------
    compliance_flags.extend(validate_staff_schedule(staff_schedule))
    compliance_flags.extend(validate_class_sizes(all_entries))
    compliance_flags.extend(validate_pullout_limits(all_entries, students_by_id))

    # ---------------------------------------------------------
    # 6. Build ScheduleProposal records
    # ---------------------------------------------------------
    entries_by_student: Dict[str, List[Dict[str, Any]]] = {}

    for entry in all_entries:
        entries_by_student.setdefault(entry["student_id"], []).append(entry)

    for student in ranked_students:
        student_id = student.get("student_id")
        student_name = full_student_name(student)

        if not student_id:
            continue

        student_entries = entries_by_student.get(student_id, [])

        student_entries.sort(
            key=lambda entry: (
                DAYS.index(entry["day_of_week"]),
                int(entry["period"])
            )
        )

        critical_count = sum(
            1
            for flag in compliance_flags
            if flag.get("student_id") == student_id
            and flag.get("severity") == "critical"
        )

        schedule_proposals.append({
            "student_id": student_id,
            "student_name": student_name,
            "school_year": school_year,
            "proposed_by": "scheduler-engine",
            "proposed_by_name": "Scheduler Engine",
            "entries": [
                {
                    "day_of_week": entry["day_of_week"],
                    "period": entry["period"],
                    "subject": entry["subject"],
                    "teacher": entry["teacher"],
                    "service_type": entry["service_type"],
                    "is_pullout": entry["is_pullout"],
                    "is_flex_period": entry["is_flex_period"]
                }
                for entry in student_entries
            ],
            "compliance_check_passed": critical_count == 0,
            "open_critical_flags": critical_count,
            "status": "draft"
        })

    # ---------------------------------------------------------
    # 7. Return everything to API layer
    # ---------------------------------------------------------
    return {
        "success": True,
        "students_received": len(students),

        "ranked_students": [
            {
                "student_id": student.get("student_id"),
                "student_name": full_student_name(student),
                "has_iep": bool(student.get("has_iep")),
                "priority_score": priority_score(student),
                "iep_services": student.get("iep_services") or [],
                "enl_minutes_required": student.get("enl_minutes_required") or 0,
                "mtss_tier": student.get("mtss_tier"),
                "grade_group": period_config.get_group_for_student(student),
            }
            for student in ranked_students
        ],

        "schedule_entries": all_entries,
        "schedule_proposals": schedule_proposals,
        "compliance_flags": compliance_flags,
        "flex_groups": flex_groups,
        "flex_group_students": student_flex_group_rows,
        "staff_schedule": staff_schedule,
        "period_config": {
            "period_times": period_config.period_times,
            "grade_groups": period_config.grade_groups,
            "group_periods": period_config.group_periods,
        },

        "summary": {
            "schedule_entries_created": len(all_entries),
            "schedule_proposals_created": len(schedule_proposals),
            "compliance_flags_created": len(compliance_flags),
            "flex_groups_created": len(flex_groups),
            "flex_group_students_created": len(student_flex_group_rows),
            "staff_members_scheduled": len(staff_schedule)
        }
    }