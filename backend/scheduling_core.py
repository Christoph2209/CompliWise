"""
scheduling_core.py

Shared foundation for CompliWise's scheduling engine: constants,
PeriodConfig, and small helper functions used by BOTH scheduler.py
(the engine that builds a schedule) and compliance.py (the validators
that check one afterward).

This file must never import from scheduler.py or compliance.py --
it's the base of the dependency chain, not a participant in it.
"""

from typing import Any, Dict, List, Optional, Set


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
# like "K", "PK", "1", "2" ... "5") to a grade GROUP name.
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
# Recess, Specials, nor Language Block for a given group. Placeholder:
# the real master schedule shows these periods (Math, Science, etc.)
# actually vary by classroom and even by day.
GENERAL_ED_PATTERN = {
    1: "Core Instruction",
    2: "Core Instruction",
    3: "Math",
    4: "Math",
    5: "Math",
    6: "Science / Social Studies",
    7: "Core Instruction",
}

# ---------------------------------------------------------------
# Specials (PE, Music, ...) config defaults
# ---------------------------------------------------------------

DEFAULT_SPECIALS_TITLES = {
    "PE Teacher": "PE",
    "Physical Education Teacher": "PE",
    "Music Teacher": "Music",
    "Art Teacher": "Art",
}

# Subjects recognized as classroom-level Specials for sizing/validation
# purposes (as opposed to individually-scheduled pullout services like
# SETSS/ENL, which use MAX_SERVICE_GROUP_SIZE instead).
KNOWN_SPECIALS_SUBJECTS = {"PE", "Music", "Art"}

# PE carries a legal weekly-minutes mandate rather than a fixed session
# count. build_specials_schedule() derives PE's actual session count
# from this and SPECIALS_SESSION_LENGTH_MINUTES["PE"].
SPECIALS_MANDATED_MINUTES_PER_WEEK = {
    "PE": 90,
}

SPECIALS_SESSION_LENGTH_MINUTES = {
    "PE": 45,
    "Music": 45,
    "Art": 45,
}
DEFAULT_SPECIALS_SESSION_LENGTH_MINUTES = 45

# Subjects with NO legal minute mandate (Music) are booked toward this
# many sessions/week as a target, not a requirement.
DEFAULT_SPECIALS_SESSIONS_PER_WEEK = {
    "PE": 2,
    "Music": 2,
    "Art": 1,
}

# Whole-classroom class, sized like a gen-ed homeroom class but with
# headroom for two homerooms to combine into one session.
MAX_GEN_ED_CLASS_SIZE = 32
MAX_SPECIALS_CLASS_SIZE = MAX_GEN_ED_CLASS_SIZE * 2


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
        specials_titles: Optional[Dict[str, str]] = None,
        specials_sessions_per_week: Optional[Dict[str, int]] = None,
        allow_specials_merge: bool = True,
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
        self.specials_titles: Dict[str, str] = (
            dict(specials_titles) if specials_titles else dict(DEFAULT_SPECIALS_TITLES)
        )
        self.specials_sessions_per_week: Dict[str, int] = (
            dict(specials_sessions_per_week)
            if specials_sessions_per_week
            else dict(DEFAULT_SPECIALS_SESSIONS_PER_WEEK)
        )
        self.allow_specials_merge: bool = allow_specials_merge
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

    def get_group_for_grade(self, grade: Any) -> str:
        key = str(grade).strip().upper() if grade is not None else ""
        group = self.grade_groups.get(key)
        if group:
            return group
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
        Lunch/Recess slot."""
        assignment = self.group_periods[self.get_group_for_student(student)]
        return set(self.periods) - {assignment["flex"], assignment["lunch"]}

    def subject_for_period(self, student: Dict[str, Any], period: int, day: Optional[str] = None) -> str:
        """What a student's day looks like at a given period, once
        FLEX/Lunch/Language Block are accounted for. Specials aren't
        resolved here -- they aren't tied to a fixed period, so
        build_specials_schedule() books them directly."""
        if period == self.flex_period(student):
            return "FLEX"
        if period == self.lunch_period(student):
            return "Lunch/Recess"
        return self.general_ed_pattern.get(period, "Core Instruction")

    def period_duration_minutes(self, period: int) -> int:
        """
        Actual clock-minutes for a period, parsed from period_times
        (e.g. "8:10-8:55" -> 45). Times are stored in 12-hour format
        without AM/PM markers, so a naive hour*60+minute parse breaks
        for any period crossing the 12:00 boundary ("1:20" parses as
        80, smaller than "12:30"'s 750, producing a negative duration).
        Since the whole schedule is a single continuous school day, if
        the parsed end time is smaller than the start time we assume
        it means the next 12-hour cycle and add 720 minutes to correct
        it.
        """
        time_range = self.period_times.get(period)
        if not time_range:
            return DEFAULT_SESSION_LENGTH_MINUTES
        try:
            start_str, end_str = time_range.split("-")
            def to_minutes(t):
                h, m = t.split(":")
                return int(h) * 60 + int(m)
            start = to_minutes(start_str)
            end = to_minutes(end_str)
            if end < start:
                end += 12 * 60
            return end - start
        except (ValueError, AttributeError):
            return DEFAULT_SESSION_LENGTH_MINUTES


# ---------------------------------------------------------------
# hard limits on pullouts
# ---------------------------------------------------------------
MAX_PULLOUTS_PER_DAY = 2
MAX_SAME_SERVICE_PER_DAY = 2

MAX_SAME_SERVICE_PER_DAY_OVERRIDES = {
    "ENL": 2,
}


def max_same_service_per_day(service_type: str) -> int:
    return MAX_SAME_SERVICE_PER_DAY_OVERRIDES.get(
        service_type, MAX_SAME_SERVICE_PER_DAY
    )


MIN_DAYS_BETWEEN_SAME_SERVICE = 0

SERVICE_SESSION_LENGTH_MINUTES = {
    "ENL": 45,
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
    "tier_3": 10,
    "enrichment": 20,
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
    "FLEX": 30,
    "PE": 120,
    "Music": 35,
    "Art": 35,
}


def full_student_name(student: Dict[str, Any]) -> str:
    first = student.get("first_name", "")
    last = student.get("last_name", "")
    return f"{first} {last}".strip() or student.get("student_id", "Unknown Student")


def staff_full_name(staff: Dict[str, Any]) -> str:
    return f"{staff.get('first_name', '')} {staff.get('last_name', '')}".strip()


def get_student_services(student: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Mandated, individually-scheduled services only.

    NOTE: FLEX for MTSS tier_2/tier_3 students is intentionally NOT
    generated here. It's handled entirely by build_flex_groups() /
    apply_flex_groups_to_schedule() in scheduler.py. Do not re-add a
    FLEX block here.
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
    # above.
    enl_minutes = int(student.get("enl_minutes_required") or 0)
    if enl_minutes > 0:
        services.append({
            "subject": "ENL",
            "service_type": "ENL",
            "minutes": enl_minutes,
            "is_pullout": True
        })

    return services