from typing import Any, Dict, List, Tuple


DAYS = ["monday", "tuesday", "wednesday", "thursday", "friday"]
CORE_PERIODS = {1, 2, 3, 7, 9}
PREFERRED_SERVICE_PERIODS = {4}  # FLEX
BREAK_PERIODS = {5, 6}           # Lunch/Recess
SPECIALS_PERIODS = {8}
PERIODS = list(range(1, 10))

FLEX_PERIOD = 4

# ---------------------------------------------------------------
# NEW: hard limits on pullouts
# ---------------------------------------------------------------
MAX_PULLOUTS_PER_DAY = 3           # hard cap: a student can't be pulled
                                   # out more than this many times in one day
MAX_SAME_SERVICE_PER_DAY = 2     # hard cap: same service_type can't be
                                   # scheduled twice on the same day
                                   # (e.g. two SETSS pullouts on Monday)

# NEW: per-service override of MAX_SAME_SERVICE_PER_DAY. Some services
# (e.g. ENL with high weekly minutes) may legitimately need two
# sessions on the same day to fit the weekly total within a 5-day week.
# Falls back to MAX_SAME_SERVICE_PER_DAY if not listed here.
MAX_SAME_SERVICE_PER_DAY_OVERRIDES = {
    "ENL": 3, # ENL students often need multiple sessions per day to fit required minutes
}

def max_same_service_per_day(service_type: str) -> int:
    return MAX_SAME_SERVICE_PER_DAY_OVERRIDES.get(
        service_type, MAX_SAME_SERVICE_PER_DAY
    )
MIN_DAYS_BETWEEN_SAME_SERVICE = 0 # 0 = no minimum gap required. Set to 1+
                                   # to force services to spread across the
                                   # week (e.g. Mon/Wed/Fri instead of
                                   # Mon/Tue/Wed).

# ---------------------------------------------------------------
# NEW: session length per service type, in minutes.
#
# The old code always assumed 30-minute sessions
# (sessions_needed = minutes_per_week / 30), which is wrong for
# services that are normally delivered in longer blocks. For
# example, an ENL mandate of 360 min/week was being turned into
# 12 sessions/week (12 pullouts!) instead of the realistic
# 4-6 sessions of 60-90 minutes. That made it impossible to
# satisfy under any sane daily-pullout limit.
#
# sessions_needed = max(1, round(minutes_per_week / session_length))
# ---------------------------------------------------------------
SERVICE_SESSION_LENGTH_MINUTES = {
    "ENL": 60,
    "SETSS": 45,
    "Speech": 30,
    "OT": 30,
    "PT": 30,
    "Counseling": 30,
    "FLEX": 30,
}
DEFAULT_SESSION_LENGTH_MINUTES = 30

def session_length_for_service(service_type: str) -> int:
    return SERVICE_SESSION_LENGTH_MINUTES.get(
        service_type, DEFAULT_SESSION_LENGTH_MINUTES
    )

MAX_FLEX_GROUP_SIZE = {
    "tier_2": 10,
    "tier_3": 6,
    # NEW: was 15, but MAX_SERVICE_GROUP_SIZE["FLEX"] = 10. A 15-student
    # enrichment FLEX group always tripped the staff group-size validator.
    # Align the two so enrichment groups don't get built oversized.
    "enrichment": 10,
}

FLEX_FOCUS_BY_NEED = {
    "reading": "reading",
    "math": "math",
    "writing": "writing",
    "behavior": "behavior",
    "enl": "enl_support",
}

GENERAL_ED_PATTERN = {
    1: "HMH Into Reading - Whole Group",
    2: "HMH Into Reading - Small Group/Centers",
    3: "IM Math",
    4: "FLEX",
    5: "Lunch",
    6: "Recess",
    7: "Science / Social Studies",
    8: "Specials",
    9: "Writing / Word Study",
}

MAX_SERVICE_GROUP_SIZE = {
    "SETSS": 8,
    "ICT": 30,
    "ENL": 15,
    "Speech": 5,
    "OT": 5,
    "PT": 5,
    "Counseling": 8,
    "FLEX": 10,
}

MAX_GEN_ED_CLASS_SIZE = 30

class ScheduleIndex:
    def __init__(self):
        self.student_busy = set()
        self.teacher_busy = set()
        self.class_rosters = {}
        self.student_services_by_day = set()
        self.pullouts_by_student_day = {}
        # NEW: counts how many times (student, service_type, day) has been
        # scheduled. student_services_by_day is a set and can't represent
        # counts > 1, so same_service_limit_reached needs this separately.
        self.service_count_by_student_day = {}
        # NEW: track which days each (student, service_type) has been
        # scheduled on, so we can enforce MIN_DAYS_BETWEEN_SAME_SERVICE
        self.service_days_by_student = {}

    def student_key(self, student_id, day, period):
        return student_id, day, int(period)

    def teacher_key(self, teacher, day, period):
        return teacher, day, int(period)

    def class_key(self, teacher, day, period, subject, room):
        return teacher or "", day, int(period), subject or "", room or ""

    def is_student_busy(self, student_id, day, period):
        return self.student_key(student_id, day, period) in self.student_busy

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

    # NEW: hard check used by find_open_slot_fast
    def pullout_limit_reached(self, student_id, day):
        return self.pullouts_already_on_day(student_id, day) >= MAX_PULLOUTS_PER_DAY

    # NEW: hard check for same service_type twice in one day
    def same_service_limit_reached(self, student_id, service_type, day):
        limit = max_same_service_per_day(service_type)
        if limit <= 0:
            return False
        count = self.service_count_by_student_day.get(
            (student_id, service_type, day), 0
        )
        return count >= limit

    # NEW: hard check enforcing minimum day-gap between sessions of the
    # same service for a given student (e.g. avoid Mon+Tue for SETSS)
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

            class_key = self.class_key(teacher, day, period, subject, room)
            if class_key not in self.class_rosters:
                self.class_rosters[class_key] = set()

            self.class_rosters[class_key].add(student_id)

        if service_type:
            self.student_services_by_day.add((student_id, service_type, day))

            # NEW: increment per-day counter (handles >1 sessions/day)
            count_key = (student_id, service_type, day)
            self.service_count_by_student_day[count_key] = (
                self.service_count_by_student_day.get(count_key, 0) + 1
            )

            # NEW: record day for min-gap tracking
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

        # Rebuild index after removal. This is simpler and safer.
        self.rebuild(entries)

    def rebuild(self, entries):
        self.__init__()
        for entry in entries:
            self.add_entry(entry)


def get_flex_focus_area(student):
    """
    Base44 FLEXGroup focus_area must be one of:
    reading, math, writing, behavior, enl_support, other
    """

    enl_level = student.get("enl_level")
    if enl_level and enl_level != "none":
        return "enl_support"

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

    return "other"

def pick_flex_teacher(focus_area: str, staff_members: list, load_fn=None) -> str:
    def load(name):
        if load_fn is None:
            return 0
        return load_fn(name)

    def best(candidates):
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
    all_instructional = list({
        staff_full_name(s) for s in staff_members
        if s.get("title") not in ("Principal", "Assistant Principal", "Paraprofessional")
        and staff_full_name(s)
    })

    if focus_area == "enl_support":
        return best(enl_certified) or best(all_instructional)
    if focus_area in ("reading", "writing"):
        return best(setss_qualified) or best(gen_ed) or best(ict) or best(all_instructional)
    if focus_area == "math":
        return best(gen_ed) or best(setss_qualified) or best(ict) or best(all_instructional)
    if focus_area == "behavior":
        return best(counselors) or best(all_instructional)

    return best(gen_ed) or best(ict) or best(all_instructional)


def build_flex_groups(students, staff_members, schedule_index=None):
    groups = []
    buckets = {}
    flex_load = {}  # teacher_name -> number of FLEX group-chunks assigned

    def load_fn(name):
        return flex_load.get(name, 0)

    for student in students:
        student_id = student.get("student_id")
        if not student_id:
            continue

        mtss_tier = student.get("mtss_tier")

        if mtss_tier not in ["tier_2", "tier_3"]:
            bucket_key = ("enrichment", "other")
        else:
            focus_area = get_flex_focus_area(student)
            bucket_key = (mtss_tier, focus_area)

        if bucket_key not in buckets:
            buckets[bucket_key] = []

        buckets[bucket_key].append(student)

    for (tier, focus_area), bucket_students in buckets.items():
        if tier == "enrichment":
            max_size = MAX_FLEX_GROUP_SIZE["enrichment"]
            base_name = f"FLEX Enrichment - {focus_area}"
            base44_tier = "tier_2"
        else:
            max_size = MAX_FLEX_GROUP_SIZE.get(tier, 10)
            base_name = f"FLEX {tier.upper()} - {focus_area}"
            base44_tier = tier

        for i in range(0, len(bucket_students), max_size):
            chunk = bucket_students[i:i + max_size]
            group_number = (i // max_size) + 1

            # Pick teacher per chunk so load spreads across staff
            teacher = pick_flex_teacher(focus_area, staff_members, load_fn=load_fn)
            flex_load[teacher] = flex_load.get(teacher, 0) + 1

            for day in DAYS:
                groups.append({
                    "name": f"{base_name} Group {group_number}",
                    "tier": base44_tier,
                    "focus_area": focus_area,
                    "teacher": teacher,
                    "student_ids": [s["student_id"] for s in chunk],
                    "max_group_size": max_size,
                    "day_of_week": day,
                    "period": FLEX_PERIOD,
                    "status": "active",
                    "group_number": group_number,
                })

    return groups

def get_flex_focus_area(student):
    """
    Returns a focus area for FLEX grouping.
    For enrichment students (no MTSS tier), still derive a focus area
    from grade or homeroom so groups are descriptive and spreadable.
    """
    enl_level = student.get("enl_level")
    if enl_level and enl_level != "none":
        return "enl_support"

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

    # For enrichment students, use grade/homeroom to split into
    # descriptive groups instead of dumping everyone into "other"
    grade = str(student.get("grade") or "").strip()
    if grade:
        return f"grade_{grade}"

    homeroom = str(student.get("homeroom") or "").strip()
    if homeroom:
        return homeroom

    return "general"

def validate_class_sizes(entries):
    flags = []
    class_rosters = {}

    for entry in entries:
        if entry.get("is_pullout"):
            continue

        if entry.get("service_type") != "general_ed":
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

def score_slot_for_service(period: int, service_type: str) -> int:
    service_type = service_type.lower()

    if period in BREAK_PERIODS:
        return -10000

    if period == FLEX_PERIOD:
        return 1000

    if service_type == "enl" and period in {1, 2}:
        # ENL push-in is okay, but pull-out should still prefer FLEX.
        return 300

    if period in SPECIALS_PERIODS:
        return 150

    if period in CORE_PERIODS:
        return -1000

    return 0

def dedupe_flex_groups(flex_groups):
    """
    Collapse truly duplicate FLEX group records (same tier + focus_area +
    teacher + day + period) into one group per slot, respecting
    max_group_size.

    The old key included group_number, which prevented merging identical
    records that build_flex_groups emits once per day per chunk. Those
    duplicates should be ONE group in the schedule (same teacher, same
    period, same kids). When a slot is genuinely full, overflow students
    spill into numbered sibling groups (Group 2, Group 3, ...).
    """
    import re

    merged: dict = {}
    overflow: dict = {}  # base_key -> list of student_ids that didn't fit

    for group in flex_groups:
        base_key = (
            group.get("tier"),
            group.get("focus_area"),
            group.get("teacher"),
            group.get("day_of_week"),
            int(group.get("period")),
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
                continue  # true duplicate — skip

            if max_size is None or len(existing["student_ids"]) < max_size:
                existing["student_ids"].append(student_id)
                existing_ids.add(student_id)
            else:
                overflow_queue.append(student_id)

    result = list(merged.values())

    # Convert overflow queues into additional sibling group records.
    for base_key, student_ids in overflow.items():
        prototype = merged[base_key]
        max_size = prototype.get("max_group_size") or 10
        base_name_clean = re.sub(r" Group \d+$", "", prototype.get("name", "FLEX Group"))

        group_number = 2  # group 1 is the primary merged group
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
    return [
        staff for staff in staff_members
        if is_general_ed_teacher(staff)
    ]


def pick_gen_ed_teacher_for_student(
    student, subject, staff_members, day="", period=0, existing_entries=None
):
    homeroom = student.get("homeroom")
    grade = str(student.get("grade", "")).lower()

    gen_ed_teachers = [
        staff for staff in staff_members
        if staff.get("title") == "General Education Teacher"
    ]

    if not gen_ed_teachers:
        return ""

    # DEBUG — remove after confirming
    if not hasattr(pick_gen_ed_teacher_for_student, "_printed"):
        pick_gen_ed_teacher_for_student._printed = True
        for t in gen_ed_teachers:
            print(f"TEACHER: {staff_full_name(t)} | room={t.get('room')!r} | homeroom={t.get('homeroom')!r}")
        print(f"STUDENT homeroom={homeroom!r} grade={grade!r}")

    for teacher in gen_ed_teachers:
        teacher_room = teacher.get("room") or teacher.get("homeroom") or ""
        if homeroom and teacher_room == homeroom:
            return staff_full_name(teacher)

    for teacher in gen_ed_teachers:
        searchable = " ".join([
            str(teacher.get("grade") or ""),
            str(teacher.get("homeroom") or ""),
            str(teacher.get("room") or ""),
        ]).lower()
        if grade and grade in searchable:
            return staff_full_name(teacher)

    return staff_full_name(gen_ed_teachers[0])

def get_student_services(student: Dict[str, Any]) -> List[Dict[str, Any]]:
    services = []

    # IEP services
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
            # fallback so IEP students still get scheduled
            services.append({
                "subject": "IEP Support",
                "service_type": "SETSS",
                "minutes": 30,
                "is_pullout": True
            })

    # ENL services
    enl_minutes = int(student.get("enl_minutes_required") or 0)
    if enl_minutes > 0:
        services.append({
            "subject": "ENL",
            "service_type": "ENL",
            "minutes": enl_minutes,
            "is_pullout": True
        })

    # MTSS / FLEX services
    mtss_tier = student.get("mtss_tier")
    if mtss_tier in ["tier_2", "tier_3"]:
        services.append({
            "subject": f"FLEX {mtss_tier.upper()}",
            "service_type": "FLEX",
            "minutes": 90 if mtss_tier == "tier_3" else 60,
            "is_pullout": False
        })

    return services


def is_student_busy(
    entries: List[Dict[str, Any]],
    student_id: str,
    day: str,
    period: int
) -> bool:
    for entry in entries:
        if (
            entry["student_id"] == student_id
            and entry["day_of_week"] == day
            and entry["period"] == period
        ):
            return True

    return False

def is_teacher_busy(
    entries: List[Dict[str, Any]],
    teacher: str,
    day: str,
    period: int,
    subject: str = "",
    room: str = "",
    allow_same_class_group: bool = True,
    max_group_size: int | None = None
) -> bool:
    if not teacher:
        return False

    for entry in entries:
        if entry.get("teacher") != teacher:
            continue

        if entry.get("day_of_week") != day:
            continue

        if int(entry.get("period")) != int(period):
            continue

        if allow_same_class_group:
            same_subject = entry.get("subject") == subject
            same_room = entry.get("room", "") == room
            existing_is_pullout = entry.get("is_pullout", False)

            if same_subject and same_room and not existing_is_pullout:
                current_size = class_group_size(
                    entries=entries,
                    teacher=teacher,
                    day=day,
                    period=period,
                    subject=subject,
                    room=room
                )

                if max_group_size is None:
                    return False

                # +1 because we are checking whether adding this student
                # would exceed the limit.
                if current_size + 1 <= max_group_size:
                    return False

                return True

        return True

    return False

def find_open_slot_fast(
    index,
    student_id,
    teacher="",
    service_type="",
    is_pullout=False
):
    candidate_slots = []

    for day in DAYS:

        # ---------------------------------------------------
        # NEW: hard limits, checked once per day (not per period)
        # ---------------------------------------------------
        if is_pullout:
            # Hard cap on total pullouts for this student today.
            if index.pullout_limit_reached(student_id, day):
                continue

            # Hard cap on repeating the *same* service twice in one day
            # (e.g. two SETSS sessions on Monday).
            if index.same_service_limit_reached(student_id, service_type, day):
                continue

            # Optional: enforce a minimum gap between sessions of the
            # same service across the week (spreads SETSS/Speech/etc.
            # across Mon/Wed/Fri instead of stacking Mon/Tue).
            if index.violates_min_day_gap(student_id, service_type, day):
                continue

        for period in PERIODS:
            if index.is_student_busy(student_id, day, period):
                continue

            if index.is_teacher_busy(
                teacher=teacher,
                day=day,
                period=period,
                subject=service_type,
                room="",
                allow_same_class_group=True,
                max_group_size=MAX_SERVICE_GROUP_SIZE.get(service_type)
            ):
                continue

            score = score_slot_for_service(period, service_type)

            if is_pullout and period in CORE_PERIODS and service_type.lower() != "enl":
                score -= 1000

            if index.service_already_on_day(student_id, service_type, day):
                score -= 300

            if index.pullouts_already_on_day(student_id, day) > 0:
                score -= 200

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

def pick_teacher_for_service(service_type: str, staff_members: List[Dict[str, Any]]) -> str:
    service_lower = service_type.lower()

    for staff in staff_members:
        title = (staff.get("title") or "").lower()
        name = f"{staff.get('first_name', '')} {staff.get('last_name', '')}".strip()

        if not name:
            continue

        if service_lower == "speech" and staff.get("is_certified_slp"):
            return name

        if service_lower in ["setss", "iep support"] and staff.get("can_deliver_setss"):
            return name

        if service_lower == "enl" and staff.get("is_certified_enl"):
            return name

        if service_lower == "counseling" and (
            "counselor" in title or "psychologist" in title or "social worker" in title
        ):
            return name

    return ""

def validate_staff_schedule(staff_schedule):
    flags = []

    for teacher, days in staff_schedule.items():
        for day, periods in days.items():
            for period, blocks in periods.items():
                # NEW: blocks is now a list (one entry per distinct
                # subject/service taught by this teacher in this period)
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


# ---------------------------------------------------------------
# NEW: validate pullout limits across the final schedule
# ---------------------------------------------------------------
def validate_pullout_limits(entries, students_by_id):
    """
    Post-pass check: flag any student who ended up with more pullouts
    in a single day than MAX_PULLOUTS_PER_DAY, or repeated same-service
    pullouts on the same day. (Belt-and-suspenders in case entries were
    added outside find_open_slot_fast, e.g. manual edits.)
    """
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
    for group in flex_groups:
        day = group["day_of_week"]
        period = int(group["period"])
        teacher = group.get("teacher", "")
        focus_area = group.get("focus_area", "other")

        for student_id in group.get("student_ids", []):
            # Do not add a second FLEX entry if the student already has anything there.
            if schedule_index.is_student_busy(student_id, day, period):
                continue

            entry = {
                "student_id": student_id,
                "day_of_week": day,
                "period": period,
                "subject": group["name"],
                "teacher": teacher,
                "room": "",
                "is_pullout": False,
                "service_type": "FLEX",
                "is_flex_period": True
                }

            all_entries.append(entry)
            schedule_index.add_entry(entry)

def remove_student_entry_at_slot(entries, student_id, day, period):
    """
    Remove an existing student entry at a day/period before placing a pull-out.
    This prevents duplicate entries like:
      Math + ENL at the same time.
    """
    entries[:] = [
        entry for entry in entries
        if not (
            entry.get("student_id") == student_id
            and entry.get("day_of_week") == day
            and int(entry.get("period")) == int(period)
        )
    ]

def schedule_iep_services_first(
    students: List[Dict[str, Any]],
    staff_members: List[Dict[str, Any]] | None = None,
    school_year: str = "2026-2027"
) -> Dict[str, Any]:
    """
    Main scheduler.

    Scheduling philosophy:
    1. Students with the highest needs are handled first.
    2. Mandated IEP / ENL / MTSS services are scheduled before normal classes.
    3. FLEX groups are created for Tier 2 / Tier 3 / enrichment support.
    4. Remaining student periods are filled with general education blocks.
    5. Staff schedules are built from student assignments.
    6. Compliance / group-size flags are returned.

    Hard limits enforced:
    - MAX_PULLOUTS_PER_DAY: a student cannot be pulled out of class more
      than this many times in a single day.
    - MAX_SAME_SERVICE_PER_DAY: the same service_type cannot be scheduled
      twice in one day for the same student.
    - MIN_DAYS_BETWEEN_SAME_SERVICE: optional minimum gap (in school days)
      between sessions of the same service for a student.
    """

    staff_members = staff_members or []

    all_entries: List[Dict[str, Any]] = []
    schedule_index = ScheduleIndex()
    schedule_proposals: List[Dict[str, Any]] = []
    compliance_flags: List[Dict[str, Any]] = []
    staff_schedule: Dict[str, Any] = {}

    # ---------------------------------------------------------
    # 1. Rank students by need
    # ---------------------------------------------------------
    ranked_students = sorted(
        students,
        key=priority_score,
        reverse=True
    )

    students_by_id = {
        student["student_id"]: student
        for student in students
        if student.get("student_id")
    }

    # ---------------------------------------------------------
    # 2. Schedule required services first
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
            teacher = pick_teacher_for_service(service_type, staff_members)

            # NEW: if no qualified staff member exists for this service
            # at all, flag it once per student as a staffing gap rather
            # than a generic scheduling conflict -- the fix is "hire/
            # assign staff", not "adjust pullout limits".
            no_qualified_staff = not teacher

            scheduled_sessions = 0

            for _ in range(sessions_needed):
                slot = find_open_slot_fast(
                    index=schedule_index,
                    student_id=student_id,
                    teacher=teacher,
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
                    "is_flex_period": period == FLEX_PERIOD
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
    # 3. Build FLEX groups
    # ---------------------------------------------------------
    flex_groups = build_flex_groups(
        students=ranked_students,
        staff_members=staff_members,
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
                "focus_area": group["focus_area"],
                "teacher": group["teacher"],
                "day_of_week": group["day_of_week"],
                "period": group["period"],
            })
    
    apply_flex_groups_to_schedule(
        all_entries=all_entries,
        flex_groups=flex_groups,
        students_by_id=students_by_id,
        schedule_index=schedule_index
    )

    # Add FLEX groups to staff schedule too
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
    # 4. Fill remaining periods with gen-ed blocks
    # ---------------------------------------------------------
    for student in ranked_students:
        student_id = student.get("student_id")
        student_name = full_student_name(student)

        if not student_id:
            continue

        for day in DAYS:
            for period in PERIODS:
                if schedule_index.is_student_busy(student_id, day, period):
                    continue

                subject = GENERAL_ED_PATTERN.get(period, "General Education")
                room = student.get("homeroom") or ""

                if subject in ["Lunch", "Recess"]:
                    teacher = ""
                else:
                    teacher = pick_gen_ed_teacher_for_student(
                        student=student,
                        subject=subject,
                        staff_members=staff_members,
                        day=day,
                        period=period,
                        existing_entries=all_entries
                    )

                entry = {
                    "student_id": student_id,
                    "day_of_week": day,
                    "period": period,
                    "subject": subject,
                    "teacher": teacher,
                    "room": room,
                    "is_pullout": False,
                    "service_type": "FLEX" if subject == "FLEX" else "general_ed",
                    "is_flex_period": subject == "FLEX"
                }

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
                    service_type=entry["service_type"],
                    is_pullout=False
                )

    # ---------------------------------------------------------
    # 5. Validate staff schedules, class sizes, and pullout limits
    # ---------------------------------------------------------
    compliance_flags.extend(
        validate_staff_schedule(staff_schedule)
    )

    compliance_flags.extend(
        validate_class_sizes(all_entries)
    )

    # NEW: post-pass pullout/duplicate-service validation
    compliance_flags.extend(
        validate_pullout_limits(all_entries, students_by_id)
    )

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
                "mtss_tier": student.get("mtss_tier")
            }
            for student in ranked_students
        ],

        "schedule_entries": all_entries,
        "schedule_proposals": schedule_proposals,
        "compliance_flags": compliance_flags,
        "flex_groups": flex_groups,
        "flex_group_students": student_flex_group_rows,  # ADD THIS
        "staff_schedule": staff_schedule,

        "summary": {
            "schedule_entries_created": len(all_entries),
            "schedule_proposals_created": len(schedule_proposals),
            "compliance_flags_created": len(compliance_flags),
            "flex_groups_created": len(flex_groups),
            "flex_group_students_created": len(student_flex_group_rows),  # ADD THIS
            "staff_members_scheduled": len(staff_schedule)
        }
    }

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

    # NEW: staff_schedule[teacher][day][period] is now a LIST of blocks,
    # one per distinct subject. Previously it was a single dict, so
    # multiple FLEX groups (different subjects/rosters) taught by the
    # same teacher in the same period got merged into one oversized
    # roster and incorrectly flagged as a single group-size violation.
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

def get_general_ed_teachers(staff_members: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [
        staff for staff in staff_members
        if staff.get("title") == "General Education Teacher"
    ]

def core_subject_for_period(period: int) -> str:
    return GENERAL_ED_PATTERN.get(period, "General Education")


def is_core_subject_period(period: int) -> bool:
    subject = core_subject_for_period(period)
    return subject in CORE_SUBJECTS


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