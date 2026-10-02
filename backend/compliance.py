"""
compliance.py

Post-scheduling validation for CompliWise.

Everything here INSPECTS an already-built schedule (its entries) and
produces compliance_flags. Nothing here places students, picks
teachers, or builds groups -- that all stays in scheduler.py.

Depends only on scheduling_core.py -- never imports from scheduler.py,
to avoid a circular import (scheduler.py imports FROM this file).

Every entry is a [start_minute, end_minute) interval on a day (see
scheduler.py). Group and class sizes are measured as the PEAK number
of students present at once, because a class is split into pieces
around pull-outs: a 2A ELA block with three kids pulled for Speech
shows up as several entries with different start times, all one class.
"""

import math
from collections import Counter
from typing import Any, Dict, List, Optional, Tuple

from scheduling_core import (
    DAYS,
    day_label,
    PeriodConfig,
    ROLE_SPECIALS,
    full_student_name,
    staff_full_name,
    get_student_services,
    max_same_service_per_day,
    session_length_for_service,
    format_minute,
    format_range,
    MAX_GEN_ED_CLASS_SIZE,
    MAX_SPECIALS_CLASS_SIZE,
    MAX_SERVICE_GROUP_SIZE,
    KNOWN_SPECIALS_SUBJECTS,
    SPECIALS_MANDATED_MINUTES_PER_WEEK,
)

SERVICE_DELIVERIES = ("pullout", "push_in")

IEP_RELATED_SERVICES = {
    "speech": {"cert_field": "is_certified_slp", "label": "Speech/Language (SLP)", "service_type": "Speech"},
    "setss": {"cert_field": "can_deliver_setss", "label": "SETSS / IEP Support", "service_type": "SETSS"},
    "enl": {"cert_field": "is_certified_enl", "label": "ENL", "service_type": "ENL"},
}


def _flag(student_id, flag_type, severity, title, description,
          legal_reference="School scheduling constraint",
          affected_period="weekly schedule") -> Dict[str, Any]:
    return {
        "student_id": student_id,
        "flag_type": flag_type,
        "severity": severity,
        "title": title,
        "description": description,
        "legal_reference": legal_reference,
        "affected_period": affected_period,
        "status": "open",
    }


def _interval(entry: Dict[str, Any]) -> Tuple[int, int]:
    """An entry's [start, end). Entries saved before the master-schedule
    migration have no end time; checking them would produce wrong
    numbers, so refuse loudly instead."""
    start, end = entry.get("start_minute"), entry.get("end_minute")
    if start is None or end is None:
        raise ValueError(
            f"Schedule entry for student {entry.get('student_id')} on "
            f"{entry.get('day_of_week')} has no start/end minute -- it was saved "
            f"before the master-schedule migration. Regenerate the schedule "
            f"before running compliance checks."
        )
    return int(start), int(end)


def _is_service(entry: Dict[str, Any]) -> bool:
    return entry.get("delivery") in SERVICE_DELIVERIES


def _peak(intervals: List[Tuple[int, int]]) -> Tuple[int, Optional[int]]:
    """Most intervals overlapping at any moment, and when that happens.
    Ends sort before starts at the same minute, so back-to-back pieces
    never count as overlapping."""
    events = sorted([(s, 1) for s, _ in intervals] + [(e, -1) for _, e in intervals])
    current = peak = 0
    at = None
    for minute, delta in events:
        current += delta
        if current > peak:
            peak, at = current, minute
    return peak, at


def _subject_base(subject: str) -> str:
    """"PE - 2A" -> "PE"."""
    return (subject or "").split(" - ")[0].strip()


def get_homerooms(students: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    """
    Local copy of scheduler.py's get_homerooms -- duplicated (not
    imported) to avoid a circular import, since scheduler.py imports
    FROM this file.
    """
    homerooms: Dict[str, List[Dict[str, Any]]] = {}
    for student in students:
        homeroom = str(student.get("homeroom") or "").strip()
        if not homeroom:
            continue
        homerooms.setdefault(homeroom, []).append(student)
    return homerooms


# ---------------------------------------------------------------
# Staffing capacity (school-wide, independent of the built schedule)
# ---------------------------------------------------------------

def _instructional_minutes_per_week(period_config: PeriodConfig) -> int:
    """Earliest block start to latest block end across all grades,
    summed over the week -- an upper bound on any provider's time."""
    total = 0
    for day in DAYS:
        blocks = [b for g in period_config.grades for b in period_config.blocks_for(g, day)]
        if blocks:
            total += max(b.end for b in blocks) - min(b.start for b in blocks)
    return total


def _specials_capacity_per_teacher(period_config: PeriodConfig) -> int:
    """Most Specials blocks one teacher can cover in a week: per day,
    the largest set of non-overlapping Specials blocks across grades
    (greedy by end time is optimal for interval scheduling)."""
    total = 0
    for day in DAYS:
        intervals = sorted(
            {
                (b.start, b.end)
                for g in period_config.grades
                for b in period_config.blocks_for(g, day)
                if period_config.role(b.subject) == ROLE_SPECIALS
            },
            key=lambda iv: iv[1],
        )
        last_end = -1
        for start, end in intervals:
            if start >= last_end:
                total += 1
                last_end = end
    return total


def _specials_teachers(staff_members, period_config: PeriodConfig) -> Dict[str, List[str]]:
    """Same mapping the scheduler uses (specials_subject, else title via
    specials_titles) -- the checker must not disagree with the engine
    about who counts as a PE teacher."""
    by_subject: Dict[str, List[str]] = {}
    for staff in staff_members:
        subject = staff.get("specials_subject") or period_config.specials_titles.get(
            staff.get("title", "")
        )
        name = staff_full_name(staff)
        if subject and name:
            by_subject.setdefault(subject, []).append(name)
    return by_subject


def check_staff_coverage(
    students: List[Dict[str, Any]],
    staff_members: List[Dict[str, Any]],
    period_config: PeriodConfig,
) -> List[Dict[str, Any]]:
    """
    Aggregate, school-wide staffing check. Flags a hard staffing gap
    ("zero qualified staff") as critical, and a soft capacity gap
    ("demand exceeds what they could cover even with zero conflicts")
    as a warning.
    """
    flags: List[Dict[str, Any]] = []
    week_minutes = _instructional_minutes_per_week(period_config)

    # ---- IEP-related services (SLP, SETSS, ENL) ----
    for service_key, config in IEP_RELATED_SERVICES.items():
        qualified_count = sum(1 for s in staff_members if s.get(config["cert_field"]))

        total_sessions_needed = 0
        session_length = None
        for student in students:
            for service in get_student_services(student):
                if service["service_type"].lower() != service_key:
                    continue
                session_length = session_length_for_service(service["service_type"])
                total_sessions_needed += max(1, math.ceil(service["minutes"] / session_length))

        if total_sessions_needed == 0:
            continue

        if qualified_count == 0:
            flags.append(_flag(
                "multiple", "staffing_gap", "critical",
                f"No {config['label']} staff on record",
                f"{total_sessions_needed} weekly session(s) of {config['label']} are "
                f"required across the student population, but no staff member is "
                f"marked as qualified to deliver {config['label']}. Add or certify "
                f"a staff member for this service.",
                legal_reference="Mandated service staffing requirement",
                affected_period="school year",
            ))
            continue

        # Solo capacity: every minute of the school day spent on one-
        # student sessions. Real capacity is lower (lunch, prep, blocks
        # closed to pull-outs), but grouping multiplies it -- so:
        #   needed > solo capacity           -> info: works only if students are grouped
        #   needed > solo x max group size   -> warning: impossible even fully grouped
        solo_capacity = qualified_count * (week_minutes // session_length)
        max_group = MAX_SERVICE_GROUP_SIZE.get(config["service_type"], 8)
        if total_sessions_needed > solo_capacity * max_group:
            flags.append(_flag(
                "multiple", "staffing_capacity", "warning",
                f"{config['label']} staffing is insufficient",
                f"{total_sessions_needed} student-sessions/week of {config['label']} are "
                f"required, more than {qualified_count} qualified staff member(s) could "
                f"deliver even with every group at the max size of {max_group}. "
                f"Add staff.",
                legal_reference="Mandated service staffing requirement",
                affected_period="school year",
            ))
        elif total_sessions_needed > solo_capacity:
            flags.append(_flag(
                "multiple", "staffing_relies_on_grouping", "info",
                f"{config['label']} depends on group sessions",
                f"{total_sessions_needed} student-sessions/week of {config['label']} "
                f"exceed the ~{solo_capacity} one-on-one sessions {qualified_count} "
                f"qualified staff member(s) could run, so it only fits if students "
                f"are grouped. Check any IEP that requires individual sessions.",
                legal_reference="Mandated service staffing requirement",
                affected_period="school year",
            ))

    # ---- Specials (PE, Music, Art) ----
    teachers_by_subject = _specials_teachers(staff_members, period_config)
    capacity_per_teacher = _specials_capacity_per_teacher(period_config)

    homeroom_block_len: Dict[str, int] = {}
    for homeroom, roster in get_homerooms(students).items():
        grades = Counter(period_config.grade_for_student(s) for s in roster)
        grade, _ = grades.most_common(1)[0]
        if grade is None:
            continue  # the scheduler already flags students with no master schedule
        lengths = [
            b.length for day in DAYS for b in period_config.blocks_for(grade, day)
            if period_config.role(b.subject) == ROLE_SPECIALS
        ]
        if lengths:
            homeroom_block_len[homeroom] = min(lengths)

    subjects = set(period_config.specials_sessions_per_week) | set(SPECIALS_MANDATED_MINUTES_PER_WEEK)
    for subject in sorted(subjects):
        mandated = SPECIALS_MANDATED_MINUTES_PER_WEEK.get(subject)
        total_needed = sum(
            math.ceil(mandated / block_len) if mandated
            else period_config.specials_sessions_per_week.get(subject, 0)
            for block_len in homeroom_block_len.values()
        )
        if total_needed == 0:
            continue

        teacher_count = len(teachers_by_subject.get(subject, []))
        if teacher_count == 0:
            flags.append(_flag(
                "multiple", "staffing_gap", "critical" if mandated else "warning",
                f"No {subject} teacher on record",
                f"{len(homeroom_block_len)} homeroom(s) need {total_needed} {subject} "
                f"session(s)/week in total, but no staff member maps to {subject} "
                f"(by specials_subject or title). Add or designate a {subject} teacher.",
                legal_reference="Specials / mandated instructional minutes",
                affected_period="school year",
            ))
            continue

        capacity = teacher_count * capacity_per_teacher
        if total_needed > capacity:
            flags.append(_flag(
                "multiple", "staffing_capacity", "warning",
                f"{subject} staffing may be insufficient",
                f"Homerooms need {total_needed} {subject} session(s)/week, but "
                f"{teacher_count} {subject} teacher(s) can cover at most {capacity} "
                f"Specials blocks/week without combining classes. Add staff or "
                f"allow combining homerooms.",
                legal_reference="Specials / mandated instructional minutes",
                affected_period="school year",
            ))

    return flags


# ---------------------------------------------------------------
# Checks on the built schedule
# ---------------------------------------------------------------

def validate_teacher_schedules(entries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    1. A teacher may only overlap themselves within ONE class/group
       (same subject + room). Anything else is a double-booking --
       this also catches manual edits made through PUT /schedule.
    2. Service groups may not exceed MAX_SERVICE_GROUP_SIZE at any
       moment.
    """
    flags: List[Dict[str, Any]] = []
    by_teacher_day: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}
    for entry in entries:
        if entry.get("teacher"):
            by_teacher_day.setdefault((entry["teacher"], entry["day_of_week"]), []).append(entry)

    for (teacher, day), items in by_teacher_day.items():
        items.sort(key=lambda e: _interval(e)[0])
        active: List[Dict[str, Any]] = []
        reported = set()
        for entry in items:
            start, end = _interval(entry)
            active = [a for a in active if _interval(a)[1] > start]
            label = (entry.get("subject"), entry.get("room"))
            for other in active:
                other_label = (other.get("subject"), other.get("room"))
                pair = tuple(sorted([str(label), str(other_label)]))
                if other_label != label and pair not in reported:
                    reported.add(pair)
                    o_start, o_end = _interval(other)
                    flags.append(_flag(
                        "multiple", "teacher_double_booked", "critical",
                        f"{teacher} double-booked on {day_label(day)}",
                        f"{teacher} has '{other_label[0]}' ({format_range(o_start, o_end)}) "
                        f"and '{label[0]}' ({format_range(start, end)}) at the same time.",
                        affected_period=f"{day_label(day)} {format_range(start, end)}",
                    ))
            active.append(entry)

        groups: Dict[Tuple[str, str, str], List[Tuple[int, int]]] = {}
        for entry in items:
            if _is_service(entry):
                key = (entry.get("subject"), entry.get("room"), entry.get("service_type", ""))
                groups.setdefault(key, []).append(_interval(entry))
        for (subject, _room, service_type), intervals in groups.items():
            max_size = MAX_SERVICE_GROUP_SIZE.get(service_type, 8)
            peak, at = _peak(intervals)
            if peak > max_size:
                flags.append(_flag(
                    "multiple", "group_size_violation", "warning",
                    f"{teacher}'s {subject} group is too large",
                    f"{teacher} has {peak} students at once for {subject} on {day_label(day)}. "
                    f"Max for {service_type} is {max_size}.",
                    affected_period=f"{day_label(day)} {format_minute(at)}",
                ))

    return flags


def validate_class_sizes(entries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Peak students at once in each gen-ed class (homeroom blocks and
    Specials). FLEX groups are sized by the scheduler and skipped."""
    flags: List[Dict[str, Any]] = []
    classes: Dict[Tuple[str, str, str, str], List[Tuple[int, int]]] = {}

    for entry in entries:
        if entry.get("service_type") != "General Ed" or not entry.get("teacher"):
            continue
        key = (entry["teacher"], entry["day_of_week"], entry.get("subject", ""), entry.get("room", ""))
        classes.setdefault(key, []).append(_interval(entry))

    for (teacher, day, subject, _room), intervals in classes.items():
        max_allowed = (
            MAX_SPECIALS_CLASS_SIZE if _subject_base(subject) in KNOWN_SPECIALS_SUBJECTS
            else MAX_GEN_ED_CLASS_SIZE
        )
        peak, at = _peak(intervals)
        if peak > max_allowed:
            flags.append(_flag(
                "multiple", "group_size_violation", "warning",
                f"{subject} class exceeds max size",
                f"{teacher}'s {subject} class on {day_label(day)} has {peak} students at once. "
                f"Max allowed is {max_allowed}.",
                affected_period=f"{day_label(day)} {format_minute(at)}",
            ))

    return flags


def validate_block_policies(
    entries: List[Dict[str, Any]],
    period_config: PeriodConfig,
) -> List[Dict[str, Any]]:
    """Every pull-out/push-in sits in a block whose policy allows it.
    The engine never violates this; manual edits can."""
    flags: List[Dict[str, Any]] = []
    for entry in entries:
        if not _is_service(entry):
            continue
        block_subject = entry.get("block_subject")
        policy = period_config.block_policies.get(block_subject)
        if policy is None:
            continue
        key = "allow_pullout" if entry["delivery"] == "pullout" else "allow_pushin"
        if not policy[key]:
            start, end = _interval(entry)
            verb = "pulled out of" if entry["delivery"] == "pullout" else "pushed into"
            flags.append(_flag(
                entry["student_id"], "service_in_protected_block", "critical",
                f"{entry.get('service_type')} {verb} {block_subject}",
                f"A {entry.get('service_type')} session on {day_label(entry['day_of_week'])} "
                f"{format_range(start, end)} is {verb} {block_subject}, which the "
                f"master schedule rules don't allow.",
                legal_reference="Least Restrictive Environment (LRE) consideration",
                affected_period=f"{day_label(entry['day_of_week'])} {format_range(start, end)}",
            ))
    return flags


def validate_pullout_limits(
    entries: List[Dict[str, Any]],
    students_by_id: Dict[str, Dict[str, Any]],
    period_config: PeriodConfig,
) -> List[Dict[str, Any]]:
    flags: List[Dict[str, Any]] = []
    pullouts: Dict[Tuple[str, str], List[Tuple[int, int]]] = {}
    service_counts: Counter = Counter()

    for entry in entries:
        if _is_service(entry):
            service_counts[(entry["student_id"], entry["day_of_week"], entry.get("service_type", ""))] += 1
        if entry.get("delivery") == "pullout":
            pullouts.setdefault((entry["student_id"], entry["day_of_week"]), []).append(_interval(entry))

    limit = period_config.max_pullouts_per_day
    min_gap = period_config.min_gap_minutes

    for (student_id, day), intervals in pullouts.items():
        name = full_student_name(students_by_id.get(student_id, {}))
        if len(intervals) > limit:
            flags.append(_flag(
                student_id, "excessive_pullouts", "warning",
                f"{name} has too many pullouts on {day_label(day)}",
                f"{name} has {len(intervals)} pullout services on {day_label(day)}. "
                f"Max configured is {limit} per day.",
                legal_reference="Least Restrictive Environment (LRE) consideration",
                affected_period=f"{day_label(day)} (all day)",
            ))
        if min_gap > 0:
            intervals.sort()
            for (_, a_end), (b_start, _) in zip(intervals, intervals[1:]):
                if b_start - a_end < min_gap:
                    flags.append(_flag(
                        student_id, "pullouts_too_close", "warning",
                        f"{name}'s pullouts on {day_label(day)} are too close together",
                        f"{name} has only {max(0, b_start - a_end)} minutes between "
                        f"pullouts on {day_label(day)}; the configured minimum is {min_gap}.",
                        legal_reference="Least Restrictive Environment (LRE) consideration",
                        affected_period=day_label(day),
                    ))
                    break

    for (student_id, day, service_type), count in service_counts.items():
        cap = max_same_service_per_day(service_type)
        if count > cap:
            name = full_student_name(students_by_id.get(student_id, {}))
            flags.append(_flag(
                student_id, "duplicate_service_same_day", "warning",
                f"{name} has duplicate {service_type} on {day_label(day)}",
                f"{name} is scheduled for {service_type} {count} times on {day_label(day)}. "
                f"Max allowed is {cap} per day.",
                affected_period=f"{day_label(day)} (all day)",
            ))

    return flags


def required_minutes_by_service(student: Dict[str, Any]) -> Dict[str, int]:
    totals: Dict[str, int] = {}
    for svc in get_student_services(student):
        totals[svc["service_type"]] = totals.get(svc["service_type"], 0) + svc["minutes"]
    return totals


def validate_weekly_service_minutes(
    entries: List[Dict[str, Any]],
    students_by_id: Dict[str, Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    Delivered minutes per (student, service) = the real length of every
    pull-out AND push-in session. (The old check counted pull-outs only,
    so every push-in student would have been flagged as short.)
    """
    flags: List[Dict[str, Any]] = []
    delivered: Counter = Counter()

    for entry in entries:
        if not _is_service(entry):
            continue
        start, end = _interval(entry)
        delivered[(entry["student_id"], entry.get("service_type", ""))] += end - start

    for student_id, student in students_by_id.items():
        for service_type, required_min in required_minutes_by_service(student).items():
            if required_min <= 0:
                continue
            got = delivered.get((student_id, service_type), 0)
            if got < required_min:
                name = full_student_name(student)
                flags.append(_flag(
                    student_id, "insufficient_weekly_minutes", "critical",
                    f"{name} under weekly minutes for {service_type}",
                    f"{name} requires {required_min} minutes/week of {service_type}, "
                    f"but only {got} minutes are scheduled ({required_min - got}-minute "
                    f"shortfall).",
                    legal_reference="Mandated service requirement",
                ))

    return flags


def run_all_compliance_checks(
    entries: List[Dict[str, Any]],
    students_by_id: Dict[str, Dict[str, Any]],
    period_config: PeriodConfig,
    students: List[Dict[str, Any]],
    staff_members: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    Single entry point -- runs every compliance check at once.
    check_staff_coverage needs the FULL raw student/staff rosters, not
    the names of whoever happened to get scheduled -- otherwise "zero
    qualified staff exist" would be silently missed.

    period_config must be the master schedule the entries were BUILT
    with (ScheduleRun.summary_json["period_config"]), not today's
    defaults.
    """
    flags: List[Dict[str, Any]] = []
    flags.extend(validate_teacher_schedules(entries))
    flags.extend(validate_class_sizes(entries))
    flags.extend(validate_block_policies(entries, period_config))
    flags.extend(validate_pullout_limits(entries, students_by_id, period_config))
    flags.extend(validate_weekly_service_minutes(entries, students_by_id))
    flags.extend(check_staff_coverage(students, staff_members, period_config))
    return flags