"""
scheduler.py

IEP / ENL / MTSS-FLEX scheduling engine for CompliWise.

Shared constants and PeriodConfig live in scheduling_core.py.
Post-build validation lives in compliance.py. This file is just the
engine: it ranks students, builds FLEX groups, books Specials, places
mandated pullout services, and fills in remaining general-ed periods.
"""

from typing import Any, Dict, List, Optional, Set, Tuple

from scheduling_core import (
    DAYS,
    PeriodConfig,
    full_student_name,
    staff_full_name,
    get_student_services,
    max_same_service_per_day,
    session_length_for_service,
    MAX_PULLOUTS_PER_DAY,
    MAX_SAME_SERVICE_PER_DAY,
    MAX_SAME_SERVICE_PER_DAY_OVERRIDES,
    MIN_DAYS_BETWEEN_SAME_SERVICE,
    MAX_FLEX_GROUP_SIZE,
    FLEX_FOCUS_BY_NEED,
    MAX_SERVICE_GROUP_SIZE,
    MAX_GEN_ED_CLASS_SIZE,
    KNOWN_SPECIALS_SUBJECTS,
    SPECIALS_MANDATED_MINUTES_PER_WEEK,
    SPECIALS_SESSION_LENGTH_MINUTES,
    DEFAULT_SPECIALS_SESSION_LENGTH_MINUTES,
    MAX_SPECIALS_CLASS_SIZE,
)
from compliance import run_all_compliance_checks


class ScheduleIndex:
    def __init__(self):
        self.student_busy = set()
        self.teacher_busy = set()
        self.class_rosters = {}
        self.student_services_by_day = set()
        self.pullouts_by_student_day = {}
        self.service_count_by_student_day = {}
        self.service_days_by_student = {}
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
        kept = []
        for entry in entries:
            same_slot = (
                entry.get("student_id") == student_id
                and entry.get("day_of_week") == day
                and int(entry.get("period")) == int(period)
            )
            if not same_slot:
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
    grade = staff.get("grade")
    if grade is None or str(grade).strip() == "":
        return None
    return period_config.get_group_for_grade(grade)


def teacher_has_core_conflict(staff: Dict[str, Any], period: int, period_config: PeriodConfig) -> bool:
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
        candidates = [c for c in candidates if c not in exclude]
        if not candidates:
            return ""
        return min(candidates, key=load)

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


def get_homerooms(students: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    homerooms: Dict[str, List[Dict[str, Any]]] = {}
    for student in students:
        homeroom = str(student.get("homeroom") or "").strip()
        if not homeroom:
            continue
        homerooms.setdefault(homeroom, []).append(student)
    return homerooms


def get_specials_teachers(
    staff_members: List[Dict[str, Any]],
    period_config: PeriodConfig,
) -> Dict[str, List[str]]:
    by_subject: Dict[str, List[str]] = {}
    for staff in staff_members:
        subject = staff.get("specials_subject") or period_config.specials_titles.get(
            staff.get("title", "")
        )
        if not subject:
            continue
        name = staff_full_name(staff)
        if not name:
            continue
        by_subject.setdefault(subject, []).append(name)
    return by_subject


def find_mergeable_specials_class(
    schedule_index: ScheduleIndex,
    subject: str,
    max_group_size: int,
    exclude_room: str = "",
) -> Optional[Tuple[str, str, int, str]]:
    best = None

    for (teacher, day, period, subj, room), roster in schedule_index.class_rosters.items():
        if subj != subject or not room or room == exclude_room:
            continue

        current_size = len(roster)
        if current_size >= max_group_size:
            continue

        if best is None or current_size < best[4]:
            best = (teacher, day, period, room, current_size)

    if best is None:
        return None

    teacher, day, period, room, _ = best
    return teacher, day, period, room


def build_specials_schedule(
    students: List[Dict[str, Any]],
    staff_members: List[Dict[str, Any]],
    period_config: PeriodConfig,
    schedule_index: ScheduleIndex,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    entries: List[Dict[str, Any]] = []
    flags: List[Dict[str, Any]] = []

    homerooms = get_homerooms(students)
    teachers_by_subject = get_specials_teachers(staff_members, period_config)

    subjects = sorted(
        set(period_config.specials_sessions_per_week.keys())
        | set(SPECIALS_MANDATED_MINUTES_PER_WEEK.keys())
    )

    if not subjects:
        return entries, flags

    teacher_load: Dict[str, int] = {}

    def pick_teacher(subject: str, day: str, period: int, room: str) -> str:
        candidates = sorted(
            set(teachers_by_subject.get(subject, [])),
            key=lambda name: teacher_load.get(name, 0),
        )
        for name in candidates:
            if not schedule_index.is_teacher_busy(
                teacher=name,
                day=day,
                period=period,
                subject=subject,
                room=room,
                allow_same_class_group=True,
                max_group_size=MAX_SPECIALS_CLASS_SIZE,
            ):
                return name
        return ""

    def session_length(subject: str) -> int:
        return SPECIALS_SESSION_LENGTH_MINUTES.get(subject, DEFAULT_SPECIALS_SESSION_LENGTH_MINUTES)

    def sessions_needed_for(subject: str) -> int:
        mandated_minutes = SPECIALS_MANDATED_MINUTES_PER_WEEK.get(subject)
        if mandated_minutes:
            return max(1, round(mandated_minutes / session_length(subject)))
        return period_config.specials_sessions_per_week.get(subject, 0)

    for homeroom, roster in homerooms.items():
        sample = roster[0]
        grade_group = period_config.get_group_for_student(sample)
        lunch_period = period_config.group_periods[grade_group]["lunch"]

        sessions_needed = {subject: sessions_needed_for(subject) for subject in subjects}

        target_queue: List[str] = []
        max_count = max(sessions_needed.values()) if sessions_needed else 0
        for i in range(max_count):
            for subject in subjects:
                if i < sessions_needed.get(subject, 0):
                    target_queue.append(subject)

        days_used: Set[str] = set()
        minutes_achieved: Dict[str, int] = {subject: 0 for subject in subjects}

        for target_subject in target_queue:
            booked = False
            candidate_days = [d for d in DAYS if d not in days_used] + [d for d in DAYS if d in days_used]

            for subject_attempt in [target_subject] + [s for s in subjects if s != target_subject]:
                if booked:
                    break

                for day in candidate_days:
                    if booked:
                        break

                    for period in period_config.periods:
                        if period == lunch_period:
                            continue

                        free_students = [
                            s for s in roster
                            if not schedule_index.is_student_busy(s.get("student_id"), day, period)
                        ]
                        if not free_students:
                            continue

                        teacher = pick_teacher(subject_attempt, day, period, homeroom)
                        if not teacher:
                            continue

                        for student in free_students:
                            entry = {
                                "student_id": student.get("student_id"),
                                "day_of_week": day,
                                "period": period,
                                "subject": subject_attempt,
                                "teacher": teacher,
                                "room": homeroom,
                                "is_pullout": False,
                                "service_type": "general_ed",
                                "is_flex_period": False,
                            }
                            entries.append(entry)
                            schedule_index.add_entry(entry)

                        teacher_load[teacher] = teacher_load.get(teacher, 0) + 1
                        minutes_achieved[subject_attempt] = (
                            minutes_achieved.get(subject_attempt, 0) + session_length(subject_attempt)
                        )
                        days_used.add(day)
                        booked = True
                        break

            if not booked and period_config.allow_specials_merge:
                merged = find_mergeable_specials_class(
                    schedule_index, target_subject, MAX_SPECIALS_CLASS_SIZE, exclude_room=homeroom
                )
                if merged:
                    m_teacher, m_day, m_period, m_room = merged
                    free_students = [
                        s for s in roster
                        if not schedule_index.is_student_busy(s.get("student_id"), m_day, m_period)
                    ]
                    if free_students:
                        for student in free_students:
                            entry = {
                                "student_id": student.get("student_id"),
                                "day_of_week": m_day,
                                "period": m_period,
                                "subject": target_subject,
                                "teacher": m_teacher,
                                "room": m_room,
                                "is_pullout": False,
                                "service_type": "general_ed",
                                "is_flex_period": False,
                            }
                            entries.append(entry)
                            schedule_index.add_entry(entry)

                        minutes_achieved[target_subject] = (
                            minutes_achieved.get(target_subject, 0) + session_length(target_subject)
                        )
                        booked = True

                        flags.append({
                            "student_id": "multiple",
                            "flag_type": "specials_classes_combined",
                            "severity": "info",
                            "title": f"{homeroom} combined for {target_subject}",
                            "description": (
                                f"Homeroom {homeroom} had no dedicated {target_subject} "
                                f"(or substitute) specialist free this week, so it was "
                                f"combined with another homeroom's {target_subject} "
                                f"class ({m_teacher}, room {m_room}) instead of going "
                                f"unscheduled."
                            ),
                            "legal_reference": "School scheduling constraint",
                            "affected_period": f"{m_day} period {m_period}",
                            "status": "open",
                        })

            if not booked:
                flags.append({
                    "student_id": "multiple",
                    "flag_type": "unscheduled_specials_period",
                    "severity": "warning",
                    "title": f"{homeroom} missing a {target_subject} session",
                    "description": (
                        f"Homeroom {homeroom} could not be scheduled for a "
                        f"{target_subject} session this week -- no specialist, "
                        f"in {target_subject} or a substitute subject, was free "
                        f"at any open slot, and no other homeroom's class had "
                        f"room to combine into. Add staffing or open up a slot "
                        f"for this homeroom."
                    ),
                    "legal_reference": "School scheduling constraint",
                    "affected_period": "weekly schedule",
                    "status": "open",
                })

        pe_mandate = SPECIALS_MANDATED_MINUTES_PER_WEEK.get("PE")
        if pe_mandate and minutes_achieved.get("PE", 0) < pe_mandate:
            flags.append({
                "student_id": "multiple",
                "flag_type": "specials_mandate_unmet",
                "severity": "critical",
                "title": f"{homeroom} under the weekly PE minutes mandate",
                "description": (
                    f"Homeroom {homeroom} received {minutes_achieved.get('PE', 0)} "
                    f"minutes of PE this week; {pe_mandate} minutes are legally "
                    f"mandated. Music substitution and merging with other "
                    f"homerooms were both tried, but coverage still fell short -- "
                    f"add PE staffing or another open slot for this homeroom."
                ),
                "legal_reference": "Mandated Physical Education minutes requirement",
                "affected_period": "weekly schedule",
                "status": "open",
            })

    return entries, flags


def build_flex_groups(students, staff_members, period_config: PeriodConfig, schedule_index=None):
    """
    Each non-paraprofessional teacher is limited to ONE FLEX assignment
    total, across ALL grade groups/periods. Paraprofessionals are
    exempt from this cap since they don't carry their own homeroom
    class. The per-PERIOD check (already_used) still applies to
    everyone.
    """
    groups = []
    buckets = {}
    flex_load = {}
    used_teachers_by_period = {}
    used_teachers_overall = set()

    paraprofessional_names = {
        staff_full_name(s) for s in staff_members
        if s.get("title") == "Paraprofessional" and staff_full_name(s)
    }

    def load_fn(name):
        return flex_load.get(name, 0)

    for student in students:
        student_id = student.get("student_id")
        if not student_id:
            continue

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

        core_conflicted = {
            staff_full_name(s) for s in staff_members
            if staff_full_name(s) and teacher_has_core_conflict(s, flex_period, period_config)
        }

        overall_exclusions = used_teachers_overall - paraprofessional_names

        for i in range(0, len(bucket_students), max_size):
            chunk = bucket_students[i:i + max_size]
            group_number = (i // max_size) + 1

            teacher = pick_flex_teacher(
                focus_area, staff_members, load_fn=load_fn,
                exclude=already_used | core_conflicted | overall_exclusions
            )
            if not teacher:
                continue

            already_used.add(teacher)
            used_teachers_overall.add(teacher)
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
    Collapse truly duplicate FLEX group records. group_number (and
    grade_group) are part of the merge key -- Group 1 and Group 2 of
    the same bucket are DIFFERENT sets of students and must stay
    separate records.
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
            group.get("group_number"),
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

    return ""


def find_open_slot_fast(
    index: ScheduleIndex,
    student: Dict[str, Any],
    period_config: PeriodConfig,
    teacher="",
    subject="",
    service_type="",
    is_pullout=False
):
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


def apply_flex_groups_to_schedule(all_entries, flex_groups, students_by_id, schedule_index):
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


def core_subject_for_period(
    period: int,
    student: Dict[str, Any],
    period_config: PeriodConfig,
    day: Optional[str] = None,
) -> str:
    return period_config.subject_for_period(student, period, day)


def schedule_iep_services_first(
    students: List[Dict[str, Any]],
    staff_members: List[Dict[str, Any]] | None = None,
    school_year: str = "2026-2027",
    period_config: Optional[PeriodConfig] = None,
    progress_callback=None,  # NEW: optional callable(stage_index: int, message: str | None = None)
) -> Dict[str, Any]:
    """
    Main scheduler. See scheduling_core.py for PeriodConfig/constants
    and compliance.py for post-build validation.
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
    # ---------------------------------------------------------
    if progress_callback:
        progress_callback(0, "Building FLEX groups")

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
    if progress_callback:
        progress_callback(1, "Scheduling mandated IEP/ENL/related services")
        
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
    # 3.5. Schedule Specials (PE, Music) per classroom.
    # ---------------------------------------------------------
    if progress_callback:
        progress_callback(2, "Scheduling Specials (PE/Music)")
        
    specials_entries, specials_flags = build_specials_schedule(
        students=ranked_students,
        staff_members=staff_members,
        period_config=period_config,
        schedule_index=schedule_index,
    )
    all_entries.extend(specials_entries)
    compliance_flags.extend(specials_flags)

    for entry in specials_entries:
        student = students_by_id.get(entry["student_id"], {})
        add_to_staff_schedule(
            staff_schedule=staff_schedule,
            teacher=entry["teacher"],
            day=entry["day_of_week"],
            period=entry["period"],
            student_id=entry["student_id"],
            student_name=full_student_name(student),
            subject=entry["subject"],
            service_type=entry["service_type"],
            is_pullout=False
        )

    # ---------------------------------------------------------
    # 4. Fill remaining periods: FLEX / Lunch-Recess / Language Block
    #    / general-ed, all resolved per-student via period_config.
    # ---------------------------------------------------------
    if progress_callback:
        progress_callback(3, "Filling remaining periods (FLEX/Lunch/Gen-Ed)")
        
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
                    subject = period_config.general_ed_pattern.get(period, "Core Instruction")
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
    if progress_callback:
        progress_callback(4, "Running compliance validation")
    
    compliance_flags.extend(
        run_all_compliance_checks(
            entries=all_entries,
            staff_schedule=staff_schedule,
            students_by_id=students_by_id,
            period_config=period_config,
            students=students,
            staff_members=staff_members
        )
    )

    # ---------------------------------------------------------
    # 6. Build ScheduleProposal records
    # ---------------------------------------------------------
    if progress_callback:
        progress_callback(5, "Building schedule proposals")

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
            "specials_titles": period_config.specials_titles,
            "specials_sessions_per_week": period_config.specials_sessions_per_week,
            "allow_specials_merge": period_config.allow_specials_merge,
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