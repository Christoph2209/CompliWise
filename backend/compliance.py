"""
compliance.py

Post-scheduling validation for CompliWise.

Everything here INSPECTS an already-built schedule (all_entries,
staff_schedule) and produces compliance_flags. Nothing here places
students, picks teachers, or builds groups -- that all stays in
scheduler.py.

Depends only on scheduling_core.py -- never imports from scheduler.py,
to avoid a circular import (scheduler.py imports FROM this file).
"""

from typing import Any, Dict, List, Tuple

from scheduling_core import (
    DAYS,
    PeriodConfig,
    full_student_name,
    get_student_services,
    max_same_service_per_day,
    session_length_for_service,
    MAX_PULLOUTS_PER_DAY,
    MAX_GEN_ED_CLASS_SIZE,
    MAX_SPECIALS_CLASS_SIZE,
    MAX_SERVICE_GROUP_SIZE,
    KNOWN_SPECIALS_SUBJECTS,
    SPECIALS_MANDATED_MINUTES_PER_WEEK,
    SPECIALS_SESSION_LENGTH_MINUTES,
    DEFAULT_SPECIALS_SESSION_LENGTH_MINUTES,
)

IEP_RELATED_SERVICES = {
    "speech": {"cert_field": "is_certified_slp", "label": "Speech/Language (SLP)"},
    "setss": {"cert_field": "can_deliver_setss", "label": "SETSS / IEP Support"},
    "enl": {"cert_field": "is_certified_enl", "label": "ENL"},
}

SPECIALS_TITLES = {
    "PE": "Physical Education Teacher",
    "Music": "Music Teacher",
    "Art": "Art Teacher",
}


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


def check_staff_coverage(
    students: List[Dict[str, Any]],
    staff_members: List[Dict[str, Any]],
    period_config: PeriodConfig,
) -> List[Dict[str, Any]]:
    """
    Aggregate, school-wide staffing check. Runs independently of whether
    per-student scheduling actually succeeded -- flags a hard staffing
    gap ("zero qualified staff") as critical, and a soft capacity gap
    ("staff exist but total demand exceeds what they can realistically
    cover") as a warning.
    """
    flags: List[Dict[str, Any]] = []
    periods_per_week = len(DAYS) * len(period_config.periods)

    # ---- IEP-related pullout services (SLP, SETSS, ENL) ----
    for service_key, config in IEP_RELATED_SERVICES.items():
        qualified = [s for s in staff_members if s.get(config["cert_field"])]
        qualified_count = len(qualified)

        total_sessions_needed = 0
        for student in students:
            for service in get_student_services(student):
                if service["service_type"].lower() != service_key:
                    continue
                session_length = session_length_for_service(service["service_type"])
                total_sessions_needed += max(1, round(service["minutes"] / session_length))

        if total_sessions_needed == 0:
            continue

        if qualified_count == 0:
            flags.append({
                "student_id": "multiple",
                "flag_type": "staffing_gap",
                "severity": "critical",
                "title": f"No {config['label']} staff on record",
                "description": (
                    f"{total_sessions_needed} weekly session(s) of "
                    f"{config['label']} are required across the student "
                    f"population, but no staff member is marked as "
                    f"qualified to deliver {config['label']}. Add or "
                    f"certify a staff member for this service."
                ),
                "legal_reference": "Mandated service staffing requirement",
                "affected_period": "school year",
                "status": "open",
            })
            continue

        estimated_capacity = qualified_count * periods_per_week

        if total_sessions_needed > estimated_capacity:
            flags.append({
                "student_id": "multiple",
                "flag_type": "staffing_capacity",
                "severity": "warning",
                "title": f"{config['label']} staffing may be insufficient",
                "description": (
                    f"{total_sessions_needed} weekly session(s) of "
                    f"{config['label']} are required, but the "
                    f"{qualified_count} qualified staff member(s) on "
                    f"record can realistically cover at most "
                    f"~{estimated_capacity} sessions/week between them. "
                    f"Consider adding staff or reviewing service loads."
                ),
                "legal_reference": "Mandated service staffing requirement",
                "affected_period": "school year",
                "status": "open",
            })

    # ---- General specials (PE, Music, Art) ----
    homerooms = get_homerooms(students)
    num_homerooms = len(homerooms)

    for subject, title in SPECIALS_TITLES.items():
        qualified = [s for s in staff_members if s.get("title") == title]
        qualified_count = len(qualified)

        mandated_minutes = SPECIALS_MANDATED_MINUTES_PER_WEEK.get(subject)
        session_length = SPECIALS_SESSION_LENGTH_MINUTES.get(
            subject, DEFAULT_SPECIALS_SESSION_LENGTH_MINUTES
        )
        sessions_needed_per_homeroom = (
            max(1, round(mandated_minutes / session_length))
            if mandated_minutes
            else period_config.specials_sessions_per_week.get(subject, 0)
        )

        if sessions_needed_per_homeroom == 0 or num_homerooms == 0:
            continue

        total_sessions_needed = num_homerooms * sessions_needed_per_homeroom

        if qualified_count == 0:
            flags.append({
                "student_id": "multiple",
                "flag_type": "staffing_gap",
                "severity": "critical",
                "title": f"No {subject} teacher on record",
                "description": (
                    f"{num_homerooms} homeroom(s) require {subject} "
                    f"({sessions_needed_per_homeroom} session(s)/week each), "
                    f"but no staff member has the title '{title}'. Add or "
                    f"designate a {subject} teacher."
                ),
                "legal_reference": "Specials / mandated instructional minutes",
                "affected_period": "school year",
                "status": "open",
            })
            continue

        estimated_capacity = qualified_count * periods_per_week

        if total_sessions_needed > estimated_capacity:
            flags.append({
                "student_id": "multiple",
                "flag_type": "staffing_capacity",
                "severity": "warning",
                "title": f"{subject} staffing may be insufficient",
                "description": (
                    f"{num_homerooms} homeroom(s) need {total_sessions_needed} "
                    f"total {subject} session(s)/week, but the "
                    f"{qualified_count} {title}(s) on staff can realistically "
                    f"cover at most ~{estimated_capacity} sessions/week. "
                    f"Consider adding staff or merging classes further."
                ),
                "legal_reference": "Specials / mandated instructional minutes",
                "affected_period": "school year",
                "status": "open",
            })

    return flags


def validate_class_sizes(entries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
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

        max_allowed = (
            MAX_SPECIALS_CLASS_SIZE if subject in KNOWN_SPECIALS_SUBJECTS else MAX_GEN_ED_CLASS_SIZE
        )

        if class_size > max_allowed:
            flags.append({
                "student_id": "multiple",
                "flag_type": "group_size_violation",
                "severity": "warning",
                "title": f"{subject} class exceeds max size",
                "description": (
                    f"{teacher}'s {subject} class on {day}, period {period} "
                    f"has {class_size} students. Max allowed is {max_allowed}."
                ),
                "legal_reference": "School scheduling constraint",
                "affected_period": f"{day} period {period}",
                "status": "open"
            })

    return flags


def validate_staff_schedule(staff_schedule: Dict[str, Any]) -> List[Dict[str, Any]]:
    flags = []

    for teacher, days in staff_schedule.items():
        for day, periods in days.items():
            for period, blocks in periods.items():
                for block in blocks:
                    students = block["students"]
                    count = len(students)

                    if block["service_type"] == "general_ed":
                        if block["subject"] in KNOWN_SPECIALS_SUBJECTS:
                            max_size = MAX_SPECIALS_CLASS_SIZE
                        else:
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


def validate_pullout_limits(
    entries: List[Dict[str, Any]],
    students_by_id: Dict[str, Dict[str, Any]]
) -> List[Dict[str, Any]]:
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


def required_minutes_by_service(student: Dict[str, Any]) -> Dict[str, int]:
    totals: Dict[str, int] = {}
    for svc in get_student_services(student):
        totals[svc["service_type"]] = totals.get(svc["service_type"], 0) + svc["minutes"]
    return totals


def validate_weekly_service_minutes(
    entries: List[Dict[str, Any]],
    students_by_id: Dict[str, Dict[str, Any]],
    period_config: PeriodConfig,
) -> List[Dict[str, Any]]:
    """
    Sums scheduled minutes per (student, service_type) across the whole
    week, using each service's own canonical session length
    (session_length_for_service) -- the same source of truth the
    scheduler used to decide sessions_needed in the first place -- NOT
    the period's wall-clock duration. A 30-minute Speech session booked
    into a 45-minute period slot should count as 30 delivered minutes,
    not 45.
    """
    flags = []
    scheduled_minutes: Dict[Tuple[str, str], int] = {}

    for entry in entries:
        if not entry.get("is_pullout"):
            continue
        student_id = entry["student_id"]
        service_type = entry.get("service_type", "")
        if not service_type:
            continue
        duration = session_length_for_service(service_type)
        key = (student_id, service_type)
        scheduled_minutes[key] = scheduled_minutes.get(key, 0) + duration

    for student_id, student in students_by_id.items():
        required = required_minutes_by_service(student)
        for service_type, required_min in required.items():
            if required_min <= 0:
                continue
            delivered = scheduled_minutes.get((student_id, service_type), 0)
            if delivered < required_min:
                student_name = full_student_name(student)
                shortfall = required_min - delivered
                flags.append({
                    "student_id": student_id,
                    "flag_type": "insufficient_weekly_minutes",
                    "severity": "critical",
                    "title": f"{student_name} under weekly minutes for {service_type}",
                    "description": (
                        f"{student_name} requires {required_min} minutes/week of "
                        f"{service_type}, but only {delivered} minutes were "
                        f"actually scheduled this week ({shortfall}-minute "
                        f"shortfall)."
                    ),
                    "legal_reference": "Mandated service requirement",
                    "affected_period": "weekly schedule",
                    "status": "open"
                })

    return flags


def run_all_compliance_checks(
    entries: List[Dict[str, Any]],
    staff_schedule: Dict[str, Any],
    students_by_id: Dict[str, Dict[str, Any]],
    period_config: PeriodConfig,
    students: List[Dict[str, Any]],
    staff_members: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    Single entry point -- runs every compliance check at once.

    Two of the checks (validate_staff_schedule, validate_class_sizes)
    only need entries/staff_schedule from an already-built schedule.
    check_staff_coverage needs the FULL raw students/staff rosters
    (not staff_schedule.keys(), which are just teacher name strings
    from whoever happened to get scheduled -- using that instead of
    the real roster would silently miss "zero qualified staff exist"
    cases and crash on .get() calls against plain strings).
    """
    flags = []
    flags.extend(validate_staff_schedule(staff_schedule))
    flags.extend(validate_class_sizes(entries))
    flags.extend(validate_pullout_limits(entries, students_by_id))
    flags.extend(validate_weekly_service_minutes(entries, students_by_id, period_config))
    flags.extend(check_staff_coverage(students, staff_members, period_config))
    return flags