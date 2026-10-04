"""
scheduling_core.py

Shared foundation for CompliWise's scheduling engine: constants, the
master-schedule PeriodConfig, and small helper functions used by BOTH
scheduler.py (the engine that builds a schedule) and compliance.py
(the validators that check one afterward).

This file must never import from scheduler.py or compliance.py --
it's the base of the dependency chain, not a participant in it.

TIME MODEL
----------
The school does not run on shared, numbered periods. Each grade has
its own sequence of blocks set by the principal (2nd grade: Math
8:20-9:20, ELA 9:20-10:30, Specials 10:30-11:10, ...). Times are stored
as minutes since midnight (8:20 AM -> 500) and everything the engine
books is a [start, end) interval inside one of those blocks.

Each block's SUBJECT maps to a BlockPolicy that says:
  role           -- who staffs it: the homeroom teacher, a FLEX group,
                    a Specials teacher, or nobody (Lunch/Recess)
  allow_pullout  -- may a provider pull a student out of this block?
  allow_pushin   -- may a provider push into the class during it?
  pullout_score  -- how good a place it is to pull from (higher =
                    better). I-Block is designed for it; core ELA/Math
                    is protected instruction.
"""

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Tuple


# The school runs on a rotating five-day cycle, not the calendar week:
# an "A day" is whichever date the school calendar says it is, so a
# holiday shifts the cycle instead of always costing Monday's classes.
# Everything scheduled is stored against a cycle day ("A".."E").
DAYS = ["A", "B", "C", "D", "E"]

# Runs and master schedules saved before the cycle used weekday names.
LEGACY_WEEKDAYS = {
    "Monday": "A",
    "Tuesday": "B",
    "Wednesday": "C",
    "Thursday": "D",
    "Friday": "E",
}


def normalize_day(raw: Any) -> str:
    """"a" / "A" / "Monday" -> "A". Unknown values come back unchanged
    (upper-cased) so callers can report them."""
    text = str(raw or "").strip()
    return LEGACY_WEEKDAYS.get(text.title(), text.upper())


def day_index(raw: Any) -> int:
    """Position in the cycle, for sorting. Unknown days sort last."""
    day = normalize_day(raw)
    return DAYS.index(day) if day in DAYS else len(DAYS)


def day_label(day: str) -> str:
    """"A" -> "A day", for flag text."""
    return f"{day} day"


# ---------------------------------------------------------------
# Hard limits on pullouts (defined before PeriodConfig, which reads
# MAX_PULLOUTS_PER_DAY as its default)
# ---------------------------------------------------------------
MAX_PULLOUTS_PER_DAY = 2
MAX_SAME_SERVICE_PER_DAY = 2

MAX_SAME_SERVICE_PER_DAY_OVERRIDES = {
    "ENL": 3,
}


def max_same_service_per_day(service_type: str) -> int:
    return MAX_SAME_SERVICE_PER_DAY_OVERRIDES.get(
        service_type, MAX_SAME_SERVICE_PER_DAY
    )


MIN_DAYS_BETWEEN_SAME_SERVICE = 0

# Resource Room was called SETSS in older data and exports. Anything
# read from the DB or a CSV goes through canonical_service_type() so
# the engine only ever sees the current name.
RESOURCE_ROOM = "Resource Room"
SERVICE_TYPE_ALIASES = {
    "setss": RESOURCE_ROOM,
    "resource room": RESOURCE_ROOM,
}


def canonical_service_type(service_type: Optional[str]) -> Optional[str]:
    if not service_type:
        return service_type
    return SERVICE_TYPE_ALIASES.get(str(service_type).strip().lower(), service_type)


SERVICE_SESSION_LENGTH_MINUTES = {
    "ENL": 45,
    RESOURCE_ROOM: 45,
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


# ---------------------------------------------------------------
# Block roles and default policies
# ---------------------------------------------------------------
ROLE_HOMEROOM = "homeroom"   # homeroom teacher teaches it (ELA, Math, SS/Sci)
ROLE_FLEX = "flex"           # intervention block -- FLEX groups are built here
ROLE_SPECIALS = "specials"   # PE/Music/Art teacher takes the class (homeroom teacher's prep)
ROLE_NONE = "none"           # no teacher assigned (Lunch, Recess)
VALID_ROLES = {ROLE_HOMEROOM, ROLE_FLEX, ROLE_SPECIALS, ROLE_NONE}

POLICY_KEYS = ("role", "allow_pullout", "allow_pushin", "pullout_score")

DEFAULT_BLOCK_POLICIES: Dict[str, Dict[str, Any]] = {
    "ELA":      {"role": ROLE_HOMEROOM, "allow_pullout": True,  "allow_pushin": True,  "pullout_score": -400},
    "Math":     {"role": ROLE_HOMEROOM, "allow_pullout": True,  "allow_pushin": True,  "pullout_score": -400},
    "SS/Sci":   {"role": ROLE_HOMEROOM, "allow_pullout": True,  "allow_pushin": True,  "pullout_score": -100},
    "I-Block":  {"role": ROLE_FLEX,     "allow_pullout": True,  "allow_pushin": False, "pullout_score": 1000},
    "Specials": {"role": ROLE_SPECIALS, "allow_pullout": False, "allow_pushin": False, "pullout_score": 0},
    "Lunch":    {"role": ROLE_NONE,     "allow_pullout": False, "allow_pushin": False, "pullout_score": 0},
    "Recess":   {"role": ROLE_NONE,     "allow_pullout": False, "allow_pushin": False, "pullout_score": 0},
}

# Spellings seen on real master schedules / IEP subject_area fields,
# mapped to a canonical policy name. Matching is case-insensitive.
SUBJECT_ALIASES = {
    "math": "Math",
    "ela": "ELA",
    "reading": "ELA",
    "writing": "ELA",
    "literacy": "ELA",
    "ss/sci": "SS/Sci",
    "soc st/sci": "SS/Sci",
    "social studies/science": "SS/Sci",
    "science / social studies": "SS/Sci",
    "science": "SS/Sci",
    "social studies": "SS/Sci",
    "i-block": "I-Block",
    "iblock": "I-Block",
    "i block": "I-Block",
    "flex": "I-Block",
    "specials": "Specials",
    "lunch": "Lunch",
    "lunch/recess": "Lunch",
    "recess": "Recess",
}

# Which block subjects a provider may push into, per service. A
# StudentService.subject_area that names an allowed push-in subject
# overrides this (e.g. Resource Room with subject_area "Math" -> Math only).
DEFAULT_PUSHIN_SUBJECTS: Dict[str, List[str]] = {
    "ENL": ["ELA", "SS/Sci"],   # integrated ENL is delivered inside content instruction
    "ICT": ["ELA", "Math"],
    RESOURCE_ROOM: ["ELA", "Math"],
    "Speech": ["ELA"],
    "OT": ["ELA"],              # fine-motor / handwriting during writing
    "Counseling": ["SS/Sci"],
    "PT": [],
}

# Per-service adjustments to a block's pullout_score. ENL keeps the
# old engine's behavior (ENL was exempt from the core-period penalty):
# stand-alone ENL is commonly delivered during ELA time.
# TODO: confirm with the ENL coordinator before real data.
SERVICE_PULLOUT_BONUS: Dict[str, Dict[str, int]] = {
    "ENL": {"ELA": 600},
}

GRADE_ALIASES = {
    "KINDERGARTEN": "K",
    "KG": "K",
    "0": "K",
    "PRE-K": "PK",
    "PREK": "PK",
    "UPK": "PK",
}


# ---------------------------------------------------------------
# Default master schedule (2026-2027 SY paper schedule).
# 24-hour times so there's no AM/PM guessing in the defaults.
# UPK runs on its own arrival/dismissal day and isn't included.
# ---------------------------------------------------------------
_DEFAULT_ROWS: Dict[str, List[Tuple[str, str, str]]] = {
    "K": [
        ("Math", "08:20", "09:15"), ("I-Block", "09:15", "10:00"),
        ("ELA", "10:00", "10:35"), ("Lunch", "10:35", "11:05"), 
        ("Recess", "11:05", "11:35"), ("ELA", "11:35", "13:00"), 
        ("Specials", "13:00", "13:45"), ("SS/Sci", "13:45", "14:45"),
    ],
    "1": [
        ("ELA", "08:20", "09:00"), ("Specials", "09:00", "09:45"),
        ("Math", "09:45", "10:35"), ("Recess", "10:35", "11:05"),
        ("Lunch", "11:05", "11:35"), ("ELA", "11:35", "12:45"),
        ("I-Block", "12:45", "13:30"), ("ELA", "13:30", "13:45"),
        ("SS/Sci", "13:45", "14:45"),
    ],
    "2": [
        ("Math", "08:20", "09:20"), ("ELA", "09:20", "10:30"),
        ("Specials", "10:30", "11:15"), ("ELA", "11:15", "11:40"),
        ("Lunch", "11:40", "12:10"), ("Recess", "12:10", "12:40"),
        ("SS/Sci", "12:40", "13:25"), ("ELA", "13:25", "13:45"),
        ("I-Block", "13:45", "14:30"), ("ELA", "14:30", "14:45")
    ],
    "3": [
        ("Math", "08:20", "09:00"), ("ELA", "09:00", "9:45"),
        ("Specials", "09:45", "10:30"), ("ELA", "10:30", "11:00"),
        ("I-Block", "11:00", "11:45"),
        ("Math", "11:45", "12:45"), ("Lunch", "12:45", "13:15"),
        ("Recess", "13:15", "13:45"), ("SS/Sci", "13:45", "14:45"),
    ],
    "4": [
        ("I-Block", "08:20", "09:05"), ("Math", "09:05", "10:15"),
        ("ELA", "10:15", "11:15"), ("Specials", "11:15", "12:00"), 
        ("ELA", "12:00", "12:45"), ("Recess", "12:45", "13:15"), 
        ("Lunch", "13:15", "13:45"), ("SS/Sci", "13:45", "14:45"),
    ],
    "5": [
        ("Math", "08:20", "09:20"), ("ELA", "09:20", "10:10"),
        ("I-Block", "10:10", "10:55"), ("SS/Sci", "10:55", "11:40"),
        ("Recess", "11:40", "12:10"), ("Lunch", "12:10", "12:40"),
        ("ELA", "12:40", "14:00"), ("Specials", "14:00", "14:45"),
    ],
}

DEFAULT_MASTER_SCHEDULE: Dict[str, List[Dict[str, Any]]] = {
    grade: [{"subject": s, "start": a, "end": b} for s, a, b in rows]
    for grade, rows in _DEFAULT_ROWS.items()
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

KNOWN_SPECIALS_SUBJECTS = {"PE", "Music", "Art"}

# PE carries a legal weekly-minutes mandate rather than a fixed session
# count. The session count is derived from the length of each grade's
# Specials block: ceil(mandate / block length).
SPECIALS_MANDATED_MINUTES_PER_WEEK = {
    "PE": 90,
}

# No longer used by scheduler.py -- a Specials session is now exactly
# as long as the grade's Specials block. Kept until compliance.py is
# migrated off them.
SPECIALS_SESSION_LENGTH_MINUTES = {
    "PE": 45,
    "Music": 45,
    "Art": 45,
}
DEFAULT_SPECIALS_SESSION_LENGTH_MINUTES = 45

DEFAULT_SPECIALS_SESSIONS_PER_WEEK = {
    "PE": 2,
    "Music": 2,
    "Art": 1,
}

MAX_GEN_ED_CLASS_SIZE = 32
MAX_SPECIALS_CLASS_SIZE = MAX_GEN_ED_CLASS_SIZE * 2


# ---------------------------------------------------------------
# Time / name normalization helpers
# ---------------------------------------------------------------

def parse_clock(value: Any) -> int:
    """
    "08:20" / "8:20" / "13:45" / "1:45" / "1:45 PM" -> minutes since
    midnight. A bare time with hour 1-6 and no AM/PM is read as
    afternoon (1:45 -> 13:45): no K-5 day starts before 7 AM or runs
    past 7 PM, so this is unambiguous for a school day, unlike the old
    walk-the-periods heuristic.
    """
    text = str(value or "").strip().upper()
    if not text:
        raise ValueError("Blank time value in master schedule")
    suffix = None
    if text.endswith("AM") or text.endswith("PM"):
        suffix = text[-2:]
        text = text[:-2].strip()
    try:
        hour_str, minute_str = text.split(":")
        hour, minute = int(hour_str), int(minute_str)
    except ValueError:
        raise ValueError(f"Can't parse time '{value}' -- expected HH:MM")
    if not 0 <= minute < 60:
        raise ValueError(f"Invalid minutes in time '{value}'")
    if suffix == "PM" and hour != 12:
        hour += 12
    elif suffix == "AM" and hour == 12:
        hour = 0
    elif suffix is None and 1 <= hour <= 6:
        hour += 12
    if not 0 <= hour < 24:
        raise ValueError(f"Invalid hour in time '{value}'")
    return hour * 60 + minute


def format_minute(minute: int) -> str:
    """500 -> "8:20 AM", 825 -> "1:45 PM"."""
    hour, mins = divmod(int(minute), 60)
    suffix = "PM" if hour >= 12 else "AM"
    display = hour % 12 or 12
    return f"{display}:{mins:02d} {suffix}"


def minute_to_hhmm(minute: int) -> str:
    """825 -> "13:45" (the format <input type="time"> uses)."""
    hour, mins = divmod(int(minute), 60)
    return f"{hour:02d}:{mins:02d}"


def format_range(start: int, end: int) -> str:
    return f"{format_minute(start)}-{format_minute(end)}"


def normalize_subject(raw: Any, known: Iterable[str]) -> str:
    """Map a block/subject_area spelling to a canonical policy name,
    or raise -- an unrecognized subject is a config error, never a
    silent fallback."""
    text = str(raw or "").strip()
    if not text:
        raise ValueError("Block subject is blank")
    known = list(known)
    by_lower = {k.lower(): k for k in known}
    key = text.lower()
    if key in by_lower:
        return by_lower[key]
    alias = SUBJECT_ALIASES.get(key)
    if alias and alias in known:
        return alias
    raise ValueError(
        f"Unknown block subject '{text}'. Known subjects: {sorted(known)}. "
        f"Add it under block_policies to use a new subject."
    )


def normalize_grade(raw: Any) -> str:
    """"Kindergarten"/"K"/"0" -> "K", "01"/"1st"/"Grade 1" -> "1"."""
    text = str(raw or "").strip().upper()
    if text.startswith("GRADE "):
        text = text[6:].strip()
    if len(text) > 2 and text[:-2].isdigit() and text[-2:] in ("ST", "ND", "RD", "TH"):
        text = text[:-2]
    if text.isdigit():
        text = str(int(text))
    return GRADE_ALIASES.get(text, text)


@dataclass(frozen=True)
class Block:
    grade: str
    subject: str
    start: int
    end: int
    days: Tuple[str, ...]

    @property
    def length(self) -> int:
        return self.end - self.start

    @property
    def label(self) -> str:
        return f"{self.subject} {format_range(self.start, self.end)}"


class PeriodConfig:
    """
    The principal's master schedule plus every pull-out/push-in rule
    the engine needs, editable BEFORE a scheduling run. Build one from
    the admin's ScheduleGenerationConfig via from_config(); omitting it
    uses DEFAULT_MASTER_SCHEDULE.

    grade_schedules: {grade: [{"subject", "start", "end", "days"?}]}
        "days" is optional; omit it for blocks that run every cycle
        day (A-E).
    block_policies: {subject: {role, allow_pullout, allow_pushin,
        pullout_score}} -- merged over DEFAULT_BLOCK_POLICIES. A
        subject not in the defaults defines a new block type.
    pushin_subjects: {service_type: [subject, ...]} -- merged over
        DEFAULT_PUSHIN_SUBJECTS.
    """

    def __init__(
        self,
        grade_schedules: Optional[Dict[str, List[Dict[str, Any]]]] = None,
        block_policies: Optional[Dict[str, Dict[str, Any]]] = None,
        pushin_subjects: Optional[Dict[str, List[str]]] = None,
        specials_titles: Optional[Dict[str, str]] = None,
        specials_sessions_per_week: Optional[Dict[str, int]] = None,
        allow_specials_merge: bool = True,
        max_pullouts_per_day: Optional[int] = None,
        min_gap_minutes: int = 0,
        slot_step_minutes: int = 5,
        min_flex_piece_minutes: int = 10,
    ):
        self.block_policies: Dict[str, Dict[str, Any]] = {
            name: dict(policy) for name, policy in DEFAULT_BLOCK_POLICIES.items()
        }
        for raw_name, overrides in (block_policies or {}).items():
            try:
                name = normalize_subject(raw_name, self.block_policies.keys())
            except ValueError:
                name = str(raw_name).strip()  # a brand-new block type
                if not name:
                    raise ValueError("block_policies contains a blank subject name")
            base = self.block_policies.get(
                name,
                {"role": ROLE_HOMEROOM, "allow_pullout": False,
                 "allow_pushin": False, "pullout_score": 0},
            )
            unknown_keys = set(overrides) - set(POLICY_KEYS)
            if unknown_keys:
                raise ValueError(
                    f"block_policies['{name}'] has unknown key(s) {sorted(unknown_keys)}; "
                    f"allowed: {list(POLICY_KEYS)}"
                )
            self.block_policies[name] = {**base, **overrides}

        self.pushin_subjects: Dict[str, List[str]] = {
            service: list(subjects) for service, subjects in DEFAULT_PUSHIN_SUBJECTS.items()
        }
        for service, subjects in (pushin_subjects or {}).items():
            self.pushin_subjects[service] = [
                normalize_subject(s, self.block_policies.keys()) for s in subjects
            ]

        raw_schedule = grade_schedules if grade_schedules else DEFAULT_MASTER_SCHEDULE
        self.blocks_by_grade: Dict[str, List[Block]] = {}
        for raw_grade, block_defs in raw_schedule.items():
            grade = normalize_grade(raw_grade)
            if not grade:
                raise ValueError("Master schedule has a blank grade")
            if grade in self.blocks_by_grade:
                raise ValueError(f"Grade '{grade}' appears twice in the master schedule")
            blocks: List[Block] = []
            for block_def in block_defs:
                subject = normalize_subject(block_def.get("subject"), self.block_policies.keys())
                start = parse_clock(block_def.get("start"))
                end = parse_clock(block_def.get("end"))
                days = tuple(normalize_day(d) for d in (block_def.get("days") or DAYS))
                bad_days = [d for d in days if d not in DAYS]
                if bad_days:
                    raise ValueError(f"Grade {grade} block {subject} has invalid day(s) {bad_days}")
                if end <= start:
                    raise ValueError(
                        f"Grade {grade} block {subject} ends ({format_minute(end)}) "
                        f"at or before it starts ({format_minute(start)})"
                    )
                blocks.append(Block(grade, subject, start, end, days))
            blocks.sort(key=lambda b: (b.start, b.end))
            self.blocks_by_grade[grade] = blocks

        self.specials_titles: Dict[str, str] = (
            dict(specials_titles) if specials_titles else dict(DEFAULT_SPECIALS_TITLES)
        )
        self.specials_sessions_per_week: Dict[str, int] = (
            dict(specials_sessions_per_week)
            if specials_sessions_per_week
            else dict(DEFAULT_SPECIALS_SESSIONS_PER_WEEK)
        )
        # NOTE: SPECIALS_MANDATED_MINUTES_PER_WEEK is intentionally NOT
        # configurable here -- a state mandate isn't a scheduling preference.
        self.allow_specials_merge: bool = allow_specials_merge
        self.max_pullouts_per_day: int = (
            max_pullouts_per_day if max_pullouts_per_day is not None else MAX_PULLOUTS_PER_DAY
        )
        self.min_gap_minutes: int = max(0, int(min_gap_minutes or 0))
        self.slot_step_minutes: int = int(slot_step_minutes)
        self.min_flex_piece_minutes: int = int(min_flex_piece_minutes)
        self._validate()

    def _validate(self):
        """Fail loudly at config time, not silently mid-schedule-run."""
        for name, policy in self.block_policies.items():
            if policy.get("role") not in VALID_ROLES:
                raise ValueError(
                    f"Block subject '{name}' has role '{policy.get('role')}'; "
                    f"must be one of {sorted(VALID_ROLES)}"
                )
            for key in ("allow_pullout", "allow_pushin"):
                if not isinstance(policy.get(key), bool):
                    raise ValueError(f"Block subject '{name}': {key} must be true/false")
            if not isinstance(policy.get("pullout_score"), int):
                raise ValueError(f"Block subject '{name}': pullout_score must be an integer")

        if not self.blocks_by_grade:
            raise ValueError("The master schedule needs at least one grade")

        for grade, blocks in self.blocks_by_grade.items():
            if not blocks:
                raise ValueError(f"Grade {grade} has no blocks in the master schedule")
            for day in DAYS:
                todays = [b for b in blocks if day in b.days]
                for earlier, later in zip(todays, todays[1:]):
                    if later.start < earlier.end:
                        raise ValueError(
                            f"Grade {grade} on {day_label(day)}: {earlier.label} overlaps {later.label}"
                        )

        if self.max_pullouts_per_day < 0:
            raise ValueError("max_pullouts_per_day can't be negative")
        if self.slot_step_minutes <= 0:
            raise ValueError("slot_step_minutes must be positive")

    # -----------------------------------------------------------
    # Lookups
    # -----------------------------------------------------------

    @property
    def grades(self) -> List[str]:
        return list(self.blocks_by_grade.keys())

    def grade_for_student(self, student: Dict[str, Any]) -> Optional[str]:
        """The student's grade key in the master schedule, or None if
        that grade has no schedule. Callers must flag None -- there is
        deliberately no fallback grade."""
        grade = normalize_grade(student.get("grade"))
        return grade if grade in self.blocks_by_grade else None

    def blocks_for(self, grade: str, day: str) -> List[Block]:
        return [b for b in self.blocks_by_grade.get(grade, []) if day in b.days]

    def policy(self, subject: str) -> Dict[str, Any]:
        return self.block_policies[subject]

    def role(self, subject: str) -> str:
        return self.block_policies[subject]["role"]

    def pushin_subjects_for(self, service_type: str, subject_area: Optional[str] = None) -> List[str]:
        """Block subjects a provider may push into for this service. A
        subject_area that names a push-in-allowed subject wins."""
        if subject_area:
            try:
                subject = normalize_subject(subject_area, self.block_policies.keys())
            except ValueError:
                subject = None
            if subject and self.block_policies[subject]["allow_pushin"]:
                return [subject]
        return [
            s for s in self.pushin_subjects.get(service_type, [])
            if s in self.block_policies and self.block_policies[s]["allow_pushin"]
        ]

    def period_label(self, start_minute: int) -> str:
        """Label for an entry starting at start_minute, e.g. "11:00 AM".
        (Entries' `period` field now holds the start minute.)"""
        return format_minute(start_minute)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "grade_schedules": {
                grade: [
                    {
                        "subject": b.subject,
                        "start_minute": b.start,
                        "end_minute": b.end,
                        "label": format_range(b.start, b.end),
                        "days": list(b.days),
                    }
                    for b in blocks
                ]
                for grade, blocks in self.blocks_by_grade.items()
            },
            "block_policies": self.block_policies,
            "pushin_subjects": self.pushin_subjects,
            "max_pullouts_per_day": self.max_pullouts_per_day,
            "min_gap_minutes": self.min_gap_minutes,
            "allow_specials_merge": self.allow_specials_merge,
            "specials_titles": self.specials_titles,
            "specials_sessions_per_week": self.specials_sessions_per_week,
        }

    def to_config_payload(self) -> Dict[str, Any]:
        """The same shape from_config() reads, with 24-hour "HH:MM"
        times. Saved on each ScheduleRun so the run can be re-checked
        against the master schedule it was actually built with, and
        used to prefill the Generate Schedule modal."""
        return {
            "grade_schedules": [
                {
                    "grade": grade,
                    "blocks": [
                        {
                            "subject": b.subject,
                            "start_time": minute_to_hhmm(b.start),
                            "end_time": minute_to_hhmm(b.end),
                            "days": list(b.days),
                        }
                        for b in blocks
                    ],
                }
                for grade, blocks in self.blocks_by_grade.items()
            ],
            "block_policies": [
                {"subject": name, **policy} for name, policy in self.block_policies.items()
            ],
            "pullout_constraints": {
                "max_pullouts_per_day": self.max_pullouts_per_day,
                "min_gap_minutes": self.min_gap_minutes,
                "allow_specials_merge": self.allow_specials_merge,
            },
            "specials_requirements": [
                {"subject": subject, "sessions_per_week": count}
                for subject, count in self.specials_sessions_per_week.items()
            ],
        }

    @classmethod
    def from_config(cls, config) -> "PeriodConfig":
        """
        Builds a PeriodConfig from the frontend's ScheduleGenerationConfig
        payload (a pydantic model) or the same shape as a plain dict
        (what to_config_payload() saved on a ScheduleRun). Every field read here is consumed downstream in
        scheduler.py -- an admin-facing field that reaches this method
        but goes nowhere after is the silent no-op bug this project has
        hit before.

        Expected payload:
          grade_schedules: [{"grade": "2", "blocks": [
              {"subject": "Math", "start_time": "08:20", "end_time": "09:20",
               "days": ["A", "C", ...]  # optional cycle days
              }, ...]}]
          block_policies: [{"subject": "ELA", "allow_pullout": true,
              "allow_pushin": true, "pullout_score": -400,
              "role": "homeroom"}]                     # optional overrides
          pullout_constraints: {"max_pullouts_per_day", "min_gap_minutes",
              "allow_specials_merge"}
          specials_requirements: [{"subject", "sessions_per_week"}]
        """
        if isinstance(config, dict):
            field = config.get
        else:
            def field(name):
                return getattr(config, name, None)

        schedule_defs = field("grade_schedules")
        if not schedule_defs:
            raise ValueError(
                "A master schedule (grade_schedules) is required -- each grade "
                "needs its blocks before a schedule can be generated."
            )

        grade_schedules: Dict[str, List[Dict[str, Any]]] = {}
        for grade_def in schedule_defs:
            grade = grade_def.get("grade")
            block_defs = grade_def.get("blocks") or []
            if not block_defs:
                raise ValueError(f"Grade '{grade}' was submitted with no blocks.")
            grade_schedules[grade] = [
                {
                    "subject": b.get("subject"),
                    "start": b.get("start_time"),
                    "end": b.get("end_time"),
                    "days": b.get("days"),
                }
                for b in block_defs
            ]

        block_policies: Dict[str, Dict[str, Any]] = {}
        for policy_def in field("block_policies") or []:
            name = policy_def.get("subject")
            if not name:
                raise ValueError("A block policy was submitted without a subject.")
            block_policies[name] = {k: policy_def[k] for k in POLICY_KEYS if k in policy_def}

        pullout = field("pullout_constraints") or {}
        specials_defs = field("specials_requirements") or []
        specials_sessions_per_week = {
            s["subject"]: s["sessions_per_week"] for s in specials_defs if s.get("subject")
        }

        return cls(
            grade_schedules=grade_schedules,
            block_policies=block_policies or None,
            specials_sessions_per_week=specials_sessions_per_week or None,
            allow_specials_merge=pullout.get("allow_specials_merge", True),
            max_pullouts_per_day=pullout.get("max_pullouts_per_day"),
            min_gap_minutes=pullout.get("min_gap_minutes", 0),
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
    RESOURCE_ROOM: 5,
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

    is_pullout=False means the provider pushes into the student's
    class. subject_area (from StudentService.subject_area) narrows
    which class subject a push-in can happen in.

    NOTE: FLEX for MTSS tier_2/tier_3 students is intentionally NOT
    generated here. It's handled entirely by build_flex_groups() in
    scheduler.py. Do not re-add a FLEX block here.
    """
    services = []

    db_services = student.get("services")

    if db_services:
        for service in db_services:
            service_type = canonical_service_type(service.get("service_type")) or RESOURCE_ROOM
            services.append({
                "subject": canonical_service_type(service.get("subject")) or service_type,
                "service_type": service_type,
                "minutes": int(service.get("minutes") or service.get("minutes_per_week") or 30),
                "is_pullout": bool(service.get("is_pullout", True)),
                "subject_area": service.get("subject_area"),
            })
    elif student.get("has_iep"):
        services.append({
            "subject": "IEP Support",
            "service_type": RESOURCE_ROOM,
            "minutes": 30,
            "is_pullout": True,
            "subject_area": None,
        })

    enl_minutes = int(student.get("enl_minutes_required") or 0)
    if enl_minutes > 0:
        services.append({
            "subject": "ENL",
            "service_type": "ENL",
            "minutes": enl_minutes,
            "is_pullout": True,
            "subject_area": None,
        })

    return services