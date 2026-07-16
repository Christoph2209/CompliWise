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
    PeriodConfig,
    full_student_name,
    get_student_services,
    max_same_service_per_day,
    MAX_PULLOUTS_PER_DAY,
    MAX_GEN_ED_CLASS_SIZE,
    MAX_SPECIALS_CLASS_SIZE,
    MAX_SERVICE_GROUP_SIZE,
    KNOWN_SPECIALS_SUBJECTS,
)


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
    """
    Total weekly required minutes per service_type for a student,
    summed across however many raw service entries share that type.
    Reuses get_student_services() from scheduling_core so this can
    never drift out of sync with however minutes/service_type are
    actually derived there.
    """
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
    Sums ACTUAL scheduled minutes per (student, service_type) across
    the whole week -- using real period durations from
    period_config.period_duration_minutes(), NOT the
    session_length_for_service() estimate used to decide sessions_needed
    -- and flags any student whose weekly total falls short of what's
    required (e.g. enl_minutes_required from the students table).
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
        duration = period_config.period_duration_minutes(int(entry["period"]))
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
) -> List[Dict[str, Any]]:
    """Single entry point so scheduler.py calls one function instead of
    importing and chaining four. Order doesn't matter -- each
    validator is independent and just appends its own flags."""
    flags = []
    flags.extend(validate_staff_schedule(staff_schedule))
    flags.extend(validate_class_sizes(entries))
    flags.extend(validate_pullout_limits(entries, students_by_id))
    flags.extend(validate_weekly_service_minutes(entries, students_by_id, period_config))
    return flags