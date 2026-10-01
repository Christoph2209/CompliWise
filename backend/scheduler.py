"""
scheduler.py

IEP / ENL / MTSS-FLEX scheduling engine for CompliWise.

Shared constants and PeriodConfig (the principal's master schedule)
live in scheduling_core.py. Post-build validation lives in
compliance.py. This file is just the engine.

PIPELINE
  0. Validate students against the master schedule and reserve each
     homeroom teacher for their own class's teaching blocks.
  1. Mandated services. Every request (student x service) is placed
     most-constrained-first. For each session the engine scores every
     legal [start, end) inside every block of the student's grade:
       - pull-out: only blocks whose policy allows it; I-Block scores
         best, ELA/Math worst; repeated pulls from one subject are
         penalized so lost instruction is spread across the week.
       - push-in: only blocks in the service's push-in subjects; the
         provider joins the homeroom, and students from the same room
         at the same time are grouped into one session.
  2. Specials: staff each homeroom's Specials blocks (PE first).
  3. FLEX groups inside each grade's FLEX-role block (I-Block).
  4. Fill every remaining minute of every student's day from the
     master schedule (ELA with their homeroom teacher, Lunch, ...).
  5. Staff schedules: one row per teacher per class/session, built
     from everything booked above, plus each homeroom teacher's prep
     and lunch. Saved to staff_schedule_entries by the API layer.
  6. Compliance validation. 7. Proposals. 8. Return.

ENTRY TIME FIELDS
  start_minute / end_minute -- minutes since midnight, [start, end)
  period                    -- equal to start_minute. Kept so the DB's
                               (run, student, day, period) unique
                               constraint still holds: a student's
                               entries never share a start time.
  delivery                  -- "pullout" | "push_in" | "class"
"""

import logging
import math
from collections import Counter
from typing import Any, Dict, List, Optional, Set, Tuple

from scheduling_core import (
    DAYS,
    day_label,
    PeriodConfig,
    Block,
    ROLE_HOMEROOM,
    ROLE_FLEX,
    ROLE_SPECIALS,
    ROLE_NONE,
    SERVICE_PULLOUT_BONUS,
    full_student_name,
    staff_full_name,
    get_student_services,
    max_same_service_per_day,
    session_length_for_service,
    normalize_grade,
    format_range,
    MIN_DAYS_BETWEEN_SAME_SERVICE,
    MAX_FLEX_GROUP_SIZE,
    MAX_SERVICE_GROUP_SIZE,
    MAX_GEN_ED_CLASS_SIZE,
    SPECIALS_MANDATED_MINUTES_PER_WEEK,
    MAX_SPECIALS_CLASS_SIZE,
)
from compliance import run_all_compliance_checks


logger = logging.getLogger(__name__)

DELIVERY_PULLOUT = "pullout"
DELIVERY_PUSHIN = "push_in"
DELIVERY_CLASS = "class"
# Staff-schedule rows only: time a teacher isn't with students.
DELIVERY_PREP = "prep"
DELIVERY_BREAK = "break"

# Rooms aren't modeled yet; a pull-out happens in "the provider's room".
PULLOUT_ROOM = ""

SPECIALS_PRIORITY_ORDER = ["PE", "Music", "Art"]

# Plain-language text for why a session couldn't be placed. Shown to
# the principal in the shortfall flag.
REASON_TEXT = {
    "daily_pullout_cap": "the student had already hit the daily pull-out cap",
    "same_service_cap": "the student already had the daily max of this service",
    "day_gap": "the required days between sessions of this service",
    "no_allowed_block": "no block that day allows this kind of delivery",
    "block_too_short": "the allowed blocks are shorter than one session",
    "student_busy": "the student was already in another service",
    "min_gap": "the minimum gap between pull-outs",
    "provider_busy": "the provider was already booked",
    "group_full": "the provider's group at that time was full",
    "no_homeroom": "the student has no homeroom to push into",
    "no_pushin_subject": "no class subject allows push-in for this service",
}


def _overlaps(a_start: int, a_end: int, b_start: int, b_end: int) -> bool:
    return a_start < b_end and b_start < a_end


def pushin_subject_label(service_subject: str) -> str:
    return f"{service_subject} (push-in)"


def make_flag(student_id, flag_type, severity, title, description,
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


def make_entry(
    student_id: str,
    day: str,
    start: int,
    end: int,
    period_config: PeriodConfig,
    subject: str,
    block_subject: str,
    teacher: str,
    room: str,
    delivery: str,
    service_type: str,
    grade: Optional[str],
    is_flex_period: bool = False,
) -> Dict[str, Any]:
    return {
        "student_id": student_id,
        "day_of_week": day,
        "period": start,
        "start_minute": start,
        "end_minute": end,
        "period_label": period_config.period_label(start),
        "time_range": format_range(start, end),
        "subject": subject,
        "block_subject": block_subject,
        "teacher": teacher,
        "room": room,
        "is_pullout": delivery == DELIVERY_PULLOUT,
        "delivery": delivery,
        "service_type": service_type,
        "is_flex_period": is_flex_period,
        "grade": grade,
    }


class ScheduleIndex:
    """
    Interval index over everything booked so far.

    A teacher interval carries a (subject, room) label. Two bookings
    for the same teacher may overlap only if they share a label -- that
    is a group. Pull-out/push-in groups must also share the exact same
    start and end (everyone arrives and leaves together); FLEX and
    homeroom classes may be joined partway (allow_partial).
    """

    def __init__(self):
        self.student_intervals: Dict[Tuple[str, str], List[Tuple[int, int]]] = {}
        self.teacher_intervals: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}
        self.pullout_intervals_by_student_day: Dict[Tuple[str, str], List[Tuple[int, int]]] = {}
        self.service_count_by_student_day: Dict[Tuple[str, str, str], int] = {}
        self.service_days_by_student: Dict[Tuple[str, str], Set[str]] = {}
        self.pullouts_by_student_subject: Dict[Tuple[str, str], int] = {}

    # ---------------- students ----------------

    def is_student_busy(self, student_id, day, start, end) -> bool:
        return any(
            _overlaps(start, end, s, e)
            for s, e in self.student_intervals.get((student_id, day), [])
        )

    def free_pieces(self, student_id, day, start, end) -> List[Tuple[int, int]]:
        """Parts of [start, end) where the student has nothing booked."""
        busy = sorted(
            (max(s, start), min(e, end))
            for s, e in self.student_intervals.get((student_id, day), [])
            if _overlaps(start, end, s, e)
        )
        pieces: List[Tuple[int, int]] = []
        cursor = start
        for s, e in busy:
            if s > cursor:
                pieces.append((cursor, s))
            cursor = max(cursor, e)
        if cursor < end:
            pieces.append((cursor, end))
        return pieces

    # ---------------- teachers ----------------

    def teacher_intervals_on(self, teacher, day) -> List[Dict[str, Any]]:
        return self.teacher_intervals.get((teacher, day), [])

    def teacher_conflict(
        self,
        teacher,
        day,
        start,
        end,
        subject,
        room,
        max_group_size=None,
        allow_partial=False,
    ) -> Optional[str]:
        """None if the teacher can take [start, end) under this label
        (free, or joining a matching group). Otherwise a reason code."""
        if not teacher:
            return None
        overlapping = [
            iv for iv in self.teacher_intervals_on(teacher, day)
            if _overlaps(start, end, iv["start"], iv["end"])
        ]
        if not overlapping:
            return None
        for iv in overlapping:
            if (iv["subject"], iv["room"]) != (subject, room):
                return "provider_busy"
            if not allow_partial and (iv["start"], iv["end"]) != (start, end):
                return "provider_busy"
        members = {iv["student_id"] for iv in overlapping if iv["student_id"]}
        if max_group_size is not None and len(members) + 1 > max_group_size:
            return "group_full"
        return None

    def group_members(self, teacher, day, start, end, subject, room) -> List[Dict[str, Any]]:
        return [
            iv for iv in self.teacher_intervals_on(teacher, day)
            if iv["student_id"]
            and (iv["start"], iv["end"]) == (start, end)
            and (iv["subject"], iv["room"]) == (subject, room)
        ]

    def teacher_free_pieces(self, teacher, day, start, end) -> List[Tuple[int, int]]:
        """Parts of [start, end) where the teacher has nothing booked."""
        busy = sorted(
            (max(iv["start"], start), min(iv["end"], end))
            for iv in self.teacher_intervals_on(teacher, day)
            if _overlaps(start, end, iv["start"], iv["end"])
        )
        pieces: List[Tuple[int, int]] = []
        cursor = start
        for s, e in busy:
            if s > cursor:
                pieces.append((cursor, s))
            cursor = max(cursor, e)
        if cursor < end:
            pieces.append((cursor, end))
        return pieces

    def reserve_teacher(self, teacher, day, start, end, subject, room,
                        service_type="General Ed", block_subject="", is_flex_period=False):
        """Book a teacher with no student attached (homeroom teaching
        blocks, a FLEX group's standing slot)."""
        if not teacher:
            return
        self.teacher_intervals.setdefault((teacher, day), []).append({
            "start": start, "end": end, "subject": subject, "room": room,
            "student_id": None, "grade": None,
            "service_type": service_type, "delivery": DELIVERY_CLASS,
            "block_subject": block_subject, "is_flex_period": is_flex_period,
        })

    # ---------------- service limits ----------------

    def pullouts_on_day(self, student_id, day) -> int:
        return len(self.pullout_intervals_by_student_day.get((student_id, day), []))

    def pullout_limit_reached(self, student_id, day, period_config: PeriodConfig) -> bool:
        return self.pullouts_on_day(student_id, day) >= period_config.max_pullouts_per_day

    def service_on_day(self, student_id, service_type, day) -> bool:
        return self.service_count_by_student_day.get((student_id, service_type, day), 0) > 0

    def same_service_limit_reached(self, student_id, service_type, day) -> bool:
        limit = max_same_service_per_day(service_type)
        if limit <= 0:
            return False
        return self.service_count_by_student_day.get((student_id, service_type, day), 0) >= limit

    def violates_min_gap(self, student_id, day, start, end, period_config: PeriodConfig) -> bool:
        min_gap = period_config.min_gap_minutes
        if min_gap <= 0:
            return False
        for s, e in self.pullout_intervals_by_student_day.get((student_id, day), []):
            if max(start - e, s - end, 0) < min_gap:
                return True
        return False

    def violates_min_day_gap(self, student_id, service_type, day) -> bool:
        if MIN_DAYS_BETWEEN_SAME_SERVICE <= 0:
            return False
        scheduled_days = self.service_days_by_student.get((student_id, service_type), set())
        day_idx = DAYS.index(day)
        return any(
            abs(day_idx - DAYS.index(other)) < MIN_DAYS_BETWEEN_SAME_SERVICE
            for other in scheduled_days
        )

    # ---------------- writes ----------------

    def add_entry(self, entry: Dict[str, Any]):
        student_id = entry["student_id"]
        day = entry["day_of_week"]
        start, end = int(entry["start_minute"]), int(entry["end_minute"])
        teacher = entry.get("teacher") or ""
        delivery = entry.get("delivery")

        self.student_intervals.setdefault((student_id, day), []).append((start, end))

        if teacher:
            self.teacher_intervals.setdefault((teacher, day), []).append({
                "start": start, "end": end,
                "subject": entry.get("subject", ""), "room": entry.get("room", ""),
                "student_id": student_id, "grade": entry.get("grade"),
                "service_type": entry.get("service_type", ""), "delivery": delivery,
                "block_subject": entry.get("block_subject", ""),
                "is_flex_period": bool(entry.get("is_flex_period")),
            })

        if delivery in (DELIVERY_PULLOUT, DELIVERY_PUSHIN):
            service_type = entry.get("service_type", "")
            count_key = (student_id, service_type, day)
            self.service_count_by_student_day[count_key] = (
                self.service_count_by_student_day.get(count_key, 0) + 1
            )
            self.service_days_by_student.setdefault((student_id, service_type), set()).add(day)

            if delivery == DELIVERY_PULLOUT:
                self.pullout_intervals_by_student_day.setdefault(
                    (student_id, day), []
                ).append((start, end))
                subject_key = (student_id, entry.get("block_subject", ""))
                self.pullouts_by_student_subject[subject_key] = (
                    self.pullouts_by_student_subject.get(subject_key, 0) + 1
                )


# ===============================================================
# Homerooms
# ===============================================================

def get_homerooms(students: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    homerooms: Dict[str, List[Dict[str, Any]]] = {}
    for student in students:
        homeroom = str(student.get("homeroom") or "").strip()
        if not homeroom:
            continue
        homerooms.setdefault(homeroom, []).append(student)
    return homerooms


def build_homeroom_teacher_map(
    staff_members: List[Dict[str, Any]],
) -> Tuple[Dict[str, str], List[Dict[str, Any]]]:
    """
    Self-contained model: every homeroom must map to exactly ONE
    General Education Teacher. Built once, up front.
    """
    homeroom_to_teachers: Dict[str, List[str]] = {}

    for staff in staff_members:
        if staff.get("title") != "General Education Teacher":
            continue
        name = staff_full_name(staff)
        homeroom = staff.get("homeroom") or staff.get("room") or ""
        if not name or not homeroom:
            continue
        homeroom_to_teachers.setdefault(homeroom, []).append(name)

    resolved: Dict[str, str] = {}
    flags: List[Dict[str, Any]] = []

    for homeroom, teachers in homeroom_to_teachers.items():
        if len(teachers) == 1:
            resolved[homeroom] = teachers[0]
        else:
            flags.append(make_flag(
                "multiple", "homeroom_teacher_data_conflict", "critical",
                f"Homeroom {homeroom} maps to {len(teachers)} teachers",
                f"Homeroom {homeroom} is claimed by multiple General Education "
                f"Teachers ({', '.join(teachers)}) via their room/homeroom fields. "
                f"Each homeroom must have exactly one teacher -- fix the "
                f"staff_members data before generating schedules.",
                legal_reference="Data integrity",
            ))

    return resolved, flags


def resolve_homerooms(
    students: List[Dict[str, Any]],
    student_grade: Dict[str, str],
    staff_members: List[Dict[str, Any]],
) -> Tuple[Dict[str, Dict[str, Any]], List[Dict[str, Any]]]:
    """homeroom -> {"grade", "teacher", "roster"}. The homeroom's grade
    is its students' grade; a homeroom spanning grades is flagged."""
    homeroom_teacher_map, flags = build_homeroom_teacher_map(staff_members)
    info: Dict[str, Dict[str, Any]] = {}

    for homeroom, roster in get_homerooms(students).items():
        grades = Counter(student_grade[s["student_id"]] for s in roster)
        grade, _ = grades.most_common(1)[0]
        if len(grades) > 1:
            flags.append(make_flag(
                "multiple", "homeroom_mixed_grades", "critical",
                f"Homeroom {homeroom} has students in grades {sorted(grades)}",
                f"Homeroom {homeroom} mixes grades {dict(grades)}. Each grade "
                f"follows its own master schedule, so the homeroom teacher was "
                f"scheduled on grade {grade}'s blocks. Fix the student grades "
                f"or split the homeroom.",
                legal_reference="Data integrity",
            ))

        teacher = homeroom_teacher_map.get(homeroom, "")
        if not teacher:
            flags.append(make_flag(
                "multiple", "no_homeroom_teacher", "critical",
                f"Homeroom {homeroom} has no assigned teacher",
                f"{len(roster)} student(s) in homeroom {homeroom} have no matching "
                f"General Education Teacher in staff_members -- give this homeroom "
                f"a teacher with a matching homeroom field, or reassign these students.",
                legal_reference="Data integrity",
            ))

        if len(roster) > MAX_GEN_ED_CLASS_SIZE:
            flags.append(make_flag(
                "multiple", "homeroom_over_capacity", "critical",
                f"Homeroom {homeroom} exceeds class size cap",
                f"Homeroom {homeroom} has {len(roster)} students, but the max "
                f"gen-ed class size is {MAX_GEN_ED_CLASS_SIZE}. Split this "
                f"homeroom or raise the cap -- this is a staffing/space decision, "
                f"not a scheduling bug.",
            ))

        info[homeroom] = {"grade": grade, "teacher": teacher, "roster": roster}

    return info, flags


def reserve_homeroom_teachers(homeroom_info, period_config: PeriodConfig, schedule_index: ScheduleIndex):
    """Block each homeroom teacher on their own class's teaching blocks
    up front, so FLEX can never borrow them mid-ELA."""
    for homeroom, info in homeroom_info.items():
        teacher = info["teacher"]
        if not teacher:
            continue
        for day in DAYS:
            for block in period_config.blocks_for(info["grade"], day):
                if period_config.role(block.subject) == ROLE_HOMEROOM:
                    schedule_index.reserve_teacher(
                        teacher, day, block.start, block.end, block.subject, homeroom,
                        block_subject=block.subject,
                    )


# ===============================================================
# Mandated services: providers, slot ranking, placement
# ===============================================================

def qualified_providers(service_type: str, staff_members: List[Dict[str, Any]]) -> List[str]:
    """Every staff member qualified for a service. Title matching for
    OT/PT/Counseling/ICT is the interim rule until StaffCertification
    exists."""
    service_lower = service_type.lower()
    names: List[str] = []

    for staff in staff_members:
        title = (staff.get("title") or "").lower()
        name = staff_full_name(staff)
        if not name:
            continue

        qualified = (
            (service_lower == "speech" and staff.get("is_certified_slp"))
            or (service_lower in ("setss", "iep support") and staff.get("can_deliver_setss"))
            or (service_lower == "enl" and staff.get("is_certified_enl"))
            or (service_lower == "counseling" and (
                "counselor" in title or "psychologist" in title or "social worker" in title
            ))
            or (service_lower == "ot" and "occupational therap" in title)
            or (service_lower == "pt" and "physical therap" in title)
            or (service_lower == "ict" and "ict co-teacher" in title)
        )
        if qualified and name not in names:
            names.append(name)

    return names


def _slot_starts(block: Block, session_len: int, step: int) -> List[int]:
    starts = set(range(block.start, block.end - session_len + 1, step))
    starts.add(block.end - session_len)   # always allow ending exactly at the block's end
    return sorted(s for s in starts if s >= block.start)


def _score_candidate(
    schedule_index: ScheduleIndex,
    period_config: PeriodConfig,
    student_id: str,
    grade: str,
    service_type: str,
    delivery: str,
    block: Block,
    day: str,
    start: int,
    end: int,
    provider: str,
    label: Tuple[str, str],
) -> Tuple[int, List[str]]:
    why: List[str] = []

    if delivery == DELIVERY_PULLOUT:
        score = period_config.policy(block.subject)["pullout_score"]
        why.append(f"pull-out during {block.subject}")
        bonus = SERVICE_PULLOUT_BONUS.get(service_type, {}).get(block.subject, 0)
        if bonus:
            score += bonus
            why.append(f"{service_type} is suited to {block.subject} time")
        repeats = schedule_index.pullouts_by_student_subject.get((student_id, block.subject), 0)
        if repeats:
            score -= 150 * repeats
            why.append(f"already pulled from {block.subject} {repeats}x this week")
        pulls_today = schedule_index.pullouts_on_day(student_id, day)
        if pulls_today:
            score -= 200 * pulls_today
            why.append(f"{pulls_today} other pull-out(s) that day")
    else:
        score = 0
        why.append(f"push-in during {block.subject}")

    if schedule_index.service_on_day(student_id, service_type, day):
        score -= 300
        why.append(f"already has {service_type} that day")

    if start != block.start and end != block.end:
        score -= 50
        why.append("starts and ends mid-block")

    members = schedule_index.group_members(provider, day, start, end, *label)
    if members:
        same_grade = any(m["grade"] == grade for m in members)
        score += 250 if same_grade else 100
        why.append(f"joins an existing group of {len(members)}")

    return score, why


def rank_slots_for_service(
    schedule_index: ScheduleIndex,
    period_config: PeriodConfig,
    student_id: str,
    grade: str,
    homeroom: str,
    service: Dict[str, Any],
    provider: str,
    session_len: int,
    reasons: Optional[Counter] = None,
    limit: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """
    Every legal time for ONE session of this service with this
    provider, best first. Rejections are tallied into `reasons` (once
    per day/block, not per start minute) so a shortfall can say why.
    """
    reasons = reasons if reasons is not None else Counter()
    service_type = service["service_type"]
    delivery = DELIVERY_PULLOUT if service["is_pullout"] else DELIVERY_PUSHIN
    max_group = MAX_SERVICE_GROUP_SIZE.get(service_type)
    candidates: List[Dict[str, Any]] = []

    if delivery == DELIVERY_PUSHIN:
        if not homeroom:
            reasons["no_homeroom"] += 1
            return []
        allowed_subjects = set(period_config.pushin_subjects_for(service_type, service.get("subject_area")))
        if not allowed_subjects:
            reasons["no_pushin_subject"] += 1
            return []
        label = (pushin_subject_label(service["subject"]), homeroom)
    else:
        allowed_subjects = set()
        label = (service["subject"], PULLOUT_ROOM)

    for day in DAYS:
        if schedule_index.same_service_limit_reached(student_id, service_type, day):
            reasons["same_service_cap"] += 1
            continue
        if schedule_index.violates_min_day_gap(student_id, service_type, day):
            reasons["day_gap"] += 1
            continue
        if delivery == DELIVERY_PULLOUT and schedule_index.pullout_limit_reached(
            student_id, day, period_config
        ):
            reasons["daily_pullout_cap"] += 1
            continue

        usable_block = False
        too_short_block = False
        for block in period_config.blocks_for(grade, day):
            policy = period_config.policy(block.subject)
            if delivery == DELIVERY_PULLOUT and not policy["allow_pullout"]:
                continue
            if delivery == DELIVERY_PUSHIN and (
                block.subject not in allowed_subjects or not policy["allow_pushin"]
            ):
                continue
            if block.length < session_len:
                too_short_block = True
                continue
            usable_block = True

            block_rejections: Set[str] = set()
            for start in _slot_starts(block, session_len, period_config.slot_step_minutes):
                end = start + session_len
                if schedule_index.is_student_busy(student_id, day, start, end):
                    block_rejections.add("student_busy")
                    continue
                if delivery == DELIVERY_PULLOUT and schedule_index.violates_min_gap(
                    student_id, day, start, end, period_config
                ):
                    block_rejections.add("min_gap")
                    continue
                conflict = schedule_index.teacher_conflict(
                    provider, day, start, end, label[0], label[1], max_group
                )
                if conflict:
                    block_rejections.add(conflict)
                    continue

                score, why = _score_candidate(
                    schedule_index, period_config, student_id, grade, service_type,
                    delivery, block, day, start, end, provider, label,
                )
                candidates.append({
                    "day": day,
                    "start": start,
                    "end": end,
                    "time_range": format_range(start, end),
                    "block_subject": block.subject,
                    "delivery": delivery,
                    "provider": provider,
                    "subject": label[0],
                    "room": label[1],
                    "score": score,
                    "why": why,
                })
            for code in block_rejections:
                reasons[code] += 1

        # Short slivers (a 5-minute ELA fragment) only count as the
        # reason when they're ALL the day offers.
        if not usable_block:
            reasons["block_too_short" if too_short_block else "no_allowed_block"] += 1

    candidates.sort(key=lambda c: (-c["score"], DAYS.index(c["day"]), c["start"]))
    return candidates[:limit] if limit else candidates


def _describe_reasons(reasons: Counter) -> str:
    top = [REASON_TEXT.get(code, code) for code, _ in reasons.most_common(3)]
    return "; ".join(top) if top else "no candidate times were found"


def static_option_count(period_config: PeriodConfig, grade: str, service: Dict[str, Any],
                        session_len: int) -> int:
    """How many start times this service could ever use for this
    grade, ignoring everyone else. Small = hard to place = goes first."""
    pushin_subjects = set(
        period_config.pushin_subjects_for(service["service_type"], service.get("subject_area"))
    )
    count = 0
    for day in DAYS:
        for block in period_config.blocks_for(grade, day):
            policy = period_config.policy(block.subject)
            if service["is_pullout"]:
                if not policy["allow_pullout"]:
                    continue
            elif block.subject not in pushin_subjects or not policy["allow_pushin"]:
                continue
            if block.length >= session_len:
                count += len(_slot_starts(block, session_len, period_config.slot_step_minutes))
    return count


def place_mandated_services(
    students: List[Dict[str, Any]],
    student_grade: Dict[str, str],
    student_homeroom: Dict[str, str],
    staff_members: List[Dict[str, Any]],
    period_config: PeriodConfig,
    schedule_index: ScheduleIndex,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]]]:
    entries: List[Dict[str, Any]] = []
    flags: List[Dict[str, Any]] = []
    report: List[Dict[str, Any]] = []

    requests = []
    for student in students:
        sid = student["student_id"]
        grade = student_grade[sid]
        for service in get_student_services(student):
            session_len = session_length_for_service(service["service_type"])
            sessions_needed = max(1, math.ceil(service["minutes"] / session_len))
            options = static_option_count(period_config, grade, service, session_len)
            requests.append({
                "student": student,
                "service": service,
                "session_len": session_len,
                "sessions_needed": sessions_needed,
                "options": options,
                "priority": priority_score(student),
            })

    # Most-constrained first: fewest legal start times per session
    # needed, then the old priority score as a tiebreaker.
    requests.sort(key=lambda r: (r["options"] / r["sessions_needed"], -r["priority"]))

    provider_load: Counter = Counter()
    provider_lock: Dict[Tuple[str, str], str] = {}

    for request in requests:
        student = request["student"]
        service = request["service"]
        sid = student["student_id"]
        name = full_student_name(student)
        grade = student_grade[sid]
        homeroom = student_homeroom.get(sid, "")
        service_type = service["service_type"]
        delivery = DELIVERY_PULLOUT if service["is_pullout"] else DELIVERY_PUSHIN
        session_len = request["session_len"]
        sessions_needed = request["sessions_needed"]

        providers = qualified_providers(service_type, staff_members)
        reasons: Counter = Counter()
        scheduled = 0
        used_providers: List[str] = []

        if not providers:
            flags.append(make_flag(
                sid, "iep_violation", "critical",
                f"Could not schedule {service_type}",
                f"{name} needs {sessions_needed} session(s) of {service_type}, but no "
                f"staff member is qualified to deliver it. This is a staffing gap, "
                f"not a scheduling limit -- add or designate a qualified provider.",
                legal_reference="Mandated service requirement",
            ))
            report.append({
                "student_id": sid, "student_name": name, "service_type": service_type,
                "delivery": delivery, "sessions_needed": sessions_needed,
                "sessions_scheduled": 0, "providers": [], "blockers": {"no_qualified_staff": 1},
            })
            continue

        for _ in range(sessions_needed):
            # Continuity first: once a student has a provider for a
            # service, keep them; fall back to others only if that
            # provider has no legal time left.
            locked = provider_lock.get((sid, service_type))
            others = sorted((p for p in providers if p != locked), key=lambda p: provider_load[p])
            order = ([locked] if locked else []) + others

            best = None
            for provider in order:
                ranked = rank_slots_for_service(
                    schedule_index, period_config, sid, grade, homeroom,
                    service, provider, session_len, reasons=reasons, limit=1,
                )
                if ranked:
                    best = ranked[0]
                    break
            if best is None:
                break

            entry = make_entry(
                sid, best["day"], best["start"], best["end"], period_config,
                subject=best["subject"], block_subject=best["block_subject"],
                teacher=best["provider"], room=best["room"], delivery=delivery,
                service_type=service_type, grade=grade,
                is_flex_period=period_config.role(best["block_subject"]) == ROLE_FLEX,
            )
            entries.append(entry)
            schedule_index.add_entry(entry)
            provider_load[best["provider"]] += 1
            provider_lock.setdefault((sid, service_type), best["provider"])
            if best["provider"] not in used_providers:
                used_providers.append(best["provider"])
            scheduled += 1

        if len(used_providers) > 1:
            flags.append(make_flag(
                sid, "service_split_across_providers", "info",
                f"{service_type} split across {len(used_providers)} providers",
                f"{name}'s {service_type} sessions are with {', '.join(used_providers)} "
                f"because the first provider had no compliant time left.",
            ))

        if scheduled < sessions_needed:
            flags.append(make_flag(
                sid, "iep_violation", "critical",
                f"Could not fully schedule {service_type}",
                f"{name} needed {sessions_needed} {delivery.replace('_', '-')} session(s) "
                f"of {service_type} ({service['minutes']} min/week at {session_len} min "
                f"each), but only {scheduled} could be placed. Most common blockers: "
                f"{_describe_reasons(reasons)}.",
                legal_reference="Mandated service requirement",
            ))

        report.append({
            "student_id": sid, "student_name": name, "service_type": service_type,
            "delivery": delivery, "sessions_needed": sessions_needed,
            "sessions_scheduled": scheduled, "providers": used_providers,
            "blockers": dict(reasons.most_common(4)) if scheduled < sessions_needed else {},
        })

    return entries, flags, report


def suggest_service_slots(
    entries: List[Dict[str, Any]],
    student: Dict[str, Any],
    service: Dict[str, Any],
    staff_members: List[Dict[str, Any]],
    period_config: PeriodConfig,
    top_n: int = 5,
) -> List[Dict[str, Any]]:
    """
    For the principal's "when could this happen?" view: rank the best
    open times for one student's service against an existing run's
    entries. The student's own class time counts as free (that's what
    a pull-out replaces); their other services and every provider's
    bookings count as busy.

    `service` uses the get_student_services() shape.
    """
    sid = student.get("student_id")
    grade = period_config.grade_for_student(student)
    if grade is None:
        raise ValueError(f"Grade '{student.get('grade')}' has no master schedule")

    index = ScheduleIndex()
    for entry in entries:
        if entry.get("student_id") == sid and entry.get("delivery") == DELIVERY_CLASS:
            continue
        index.add_entry(entry)

    session_len = session_length_for_service(service["service_type"])
    homeroom = str(student.get("homeroom") or "").strip()
    suggestions: List[Dict[str, Any]] = []
    for provider in qualified_providers(service["service_type"], staff_members):
        suggestions.extend(rank_slots_for_service(
            index, period_config, sid, grade, homeroom, service, provider,
            session_len, limit=top_n,
        ))
    suggestions.sort(key=lambda c: (-c["score"], DAYS.index(c["day"]), c["start"]))
    return suggestions[:top_n]


# ===============================================================
# Specials
# ===============================================================

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


def build_specials_schedule(
    homeroom_info: Dict[str, Dict[str, Any]],
    staff_members: List[Dict[str, Any]],
    period_config: PeriodConfig,
    schedule_index: ScheduleIndex,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    The master schedule already says WHEN each homeroom has Specials;
    this decides WHICH subject and teacher each of those blocks gets.
    Each homeroom gets a plan that spaces its subjects through the
    cycle; days are then walked in order and, within a day, sibling
    homerooms take turns, so if 2A gets the PE teacher on A day, 2B
    (same block) takes Music. A session is exactly one Specials block
    long.
    """
    entries: List[Dict[str, Any]] = []
    flags: List[Dict[str, Any]] = []
    teachers_by_subject = get_specials_teachers(staff_members, period_config)

    all_subjects = set(period_config.specials_sessions_per_week) | set(
        SPECIALS_MANDATED_MINUTES_PER_WEEK
    )
    subjects = [s for s in SPECIALS_PRIORITY_ORDER if s in all_subjects] + sorted(
        all_subjects - set(SPECIALS_PRIORITY_ORDER)
    )
    if not subjects:
        return entries, flags

    for subject in subjects:
        if not teachers_by_subject.get(subject):
            flags.append(make_flag(
                "multiple", "no_specials_teacher", "warning",
                f"No {subject} teacher on staff",
                f"No staff member's title maps to {subject} (see specials_titles), "
                f"so no homeroom can be scheduled for {subject}.",
            ))

    teacher_load: Counter = Counter()
    # Once a homeroom gets a teacher for a subject, every later session
    # of that subject MUST use the same teacher.
    homeroom_subject_teacher: Dict[Tuple[str, str], str] = {}

    plans: Dict[str, Dict[str, Any]] = {}
    for homeroom, info in homeroom_info.items():
        blocks = [
            (day, block) for day in DAYS
            for block in period_config.blocks_for(info["grade"], day)
            if period_config.role(block.subject) == ROLE_SPECIALS
        ]
        if not blocks:
            continue
        block_len = min(block.length for _, block in blocks)
        needed: Dict[str, int] = {}
        for subject in subjects:
            mandate = SPECIALS_MANDATED_MINUTES_PER_WEEK.get(subject)
            needed[subject] = (
                math.ceil(mandate / block_len) if mandate
                else period_config.specials_sessions_per_week.get(subject, 0)
            )
        queue: List[str] = []
        for i in range(max(needed.values(), default=0)):
            for subject in subjects:
                if i < needed[subject]:
                    queue.append(subject)
        # Which subject each block should get. Mandated sessions are
        # spaced evenly through the cycle (3 PE in 5 blocks -> A, C, E)
        # instead of filling its first days, and each homeroom starts
        # one day later than the last so they don't all want the PE
        # teacher on the same day.
        mandated_queue = [s for s in queue if s in SPECIALS_MANDATED_MINUTES_PER_WEEK]
        optional_queue = [s for s in queue if s not in SPECIALS_MANDATED_MINUTES_PER_WEEK]
        n, k = len(blocks), min(len(mandated_queue), len(blocks))
        offset = len(plans) % n
        if k <= 1:
            slots = [offset] * k
        else:
            slots = sorted((round(i * (n - 1) / (k - 1)) + offset) % n for i in range(k))
        planned: Dict[int, str] = dict(zip(slots, mandated_queue))
        open_slots = [i for i in range(n) if i not in planned]
        planned.update(zip(open_slots, optional_queue))

        plans[homeroom] = {
            "blocks": blocks, "queue": queue, "needed": needed, "planned": planned,
            "minutes": Counter(), "unstaffed": 0,
        }

    def book(homeroom, info, day, block, teacher, label):
        for student in info["roster"]:
            sid = student["student_id"]
            for start, end in schedule_index.free_pieces(sid, day, block.start, block.end):
                entry = make_entry(
                    sid, day, start, end, period_config,
                    subject=label[0], block_subject=block.subject,
                    teacher=teacher, room=label[1], delivery=DELIVERY_CLASS,
                    service_type="General Ed", grade=info["grade"],
                )
                entries.append(entry)
                schedule_index.add_entry(entry)

    def record(plan, subject, block):
        if subject in plan["queue"]:
            plan["queue"].remove(subject)
        plan["minutes"][subject] += block.length

    def find_merge_host(subject, homeroom, day, block, size):
        locked = homeroom_subject_teacher.get((homeroom, subject))
        for name in ([locked] if locked else teachers_by_subject.get(subject, [])):
            hosts = [
                iv for iv in schedule_index.teacher_intervals_on(name, day)
                if (iv["start"], iv["end"]) == (block.start, block.end)
                and iv["subject"].startswith(f"{subject} - ")
            ]
            if not hosts:
                continue
            label = (hosts[0]["subject"], hosts[0]["room"])
            if schedule_index.teacher_conflict(
                name, day, block.start, block.end, *label
            ) is not None:
                continue
            current = len({iv["student_id"] for iv in hosts if iv["student_id"]})
            if current + size <= MAX_SPECIALS_CLASS_SIZE:
                return name, label
        return None

    def try_dedicated(homeroom, plan, info, day, block, subject):
        locked = homeroom_subject_teacher.get((homeroom, subject))
        candidates = [locked] if locked else sorted(
            teachers_by_subject.get(subject, []), key=lambda n: teacher_load[n]
        )
        label = (f"{subject} - {homeroom}", homeroom)
        for name in candidates:
            if schedule_index.teacher_conflict(name, day, block.start, block.end, *label) is None:
                book(homeroom, info, day, block, name, label)
                homeroom_subject_teacher.setdefault((homeroom, subject), name)
                teacher_load[name] += 1
                record(plan, subject, block)
                return True
        return False

    def try_merge(homeroom, plan, info, day, block, subject):
        host = find_merge_host(subject, homeroom, day, block, len(info["roster"]))
        if not host:
            return False
        name, label = host
        book(homeroom, info, day, block, name, label)
        homeroom_subject_teacher.setdefault((homeroom, subject), name)
        record(plan, subject, block)
        flags.append(make_flag(
            "multiple", "specials_classes_combined", "info",
            f"{homeroom} combined for {subject}",
            f"Homeroom {homeroom} had no dedicated {subject} teacher free, so it "
            f"joined {label[1]}'s class with {name}.",
            affected_period=f"{day_label(day)} {format_range(block.start, block.end)}",
        ))
        return True

    for day in DAYS:
        for homeroom, plan in plans.items():
            info = homeroom_info[homeroom]
            for index, (block_day, block) in enumerate(plan["blocks"]):
                if block_day != day:
                    continue
                if not any(
                    schedule_index.free_pieces(s["student_id"], day, block.start, block.end)
                    for s in info["roster"]
                ):
                    continue

                # The block's planned subject gets first try. After it,
                # mandated subjects (PE) come before target-only ones --
                # joining another homeroom's class if their teacher is
                # taken. If the mandate has fallen behind (as many
                # sessions still owed as blocks left), the plan is
                # dropped and mandated subjects go first.
                # Once targets are met, keep staffing the block anyway:
                # it's the homeroom teacher's prep.
                pending = list(dict.fromkeys(plan["queue"])) or list(subjects)
                mandated = [s for s in pending if s in SPECIALS_MANDATED_MINUTES_PER_WEEK]
                optional = [s for s in pending if s not in SPECIALS_MANDATED_MINUTES_PER_WEEK]
                planned = plan["planned"].get(index)
                mandated_owed = sum(
                    1 for s in plan["queue"] if s in SPECIALS_MANDATED_MINUTES_PER_WEEK
                )
                if planned in pending and mandated_owed < len(plan["blocks"]) - index:
                    tiers = (
                        [planned],
                        [s for s in mandated if s != planned],
                        [s for s in optional if s != planned],
                    )
                elif planned in mandated:
                    tiers = ([planned], [s for s in mandated if s != planned], optional)
                else:
                    tiers = (mandated, optional)
                booked = False
                for tier in tiers:
                    for subject in tier:
                        if try_dedicated(homeroom, plan, info, day, block, subject):
                            booked = True
                            break
                    if booked:
                        break
                    if period_config.allow_specials_merge:
                        for subject in tier:
                            if try_merge(homeroom, plan, info, day, block, subject):
                                booked = True
                                break
                    if booked:
                        break

                if not booked:
                    plan["unstaffed"] += 1

    pe_mandate = SPECIALS_MANDATED_MINUTES_PER_WEEK.get("PE")
    for homeroom, plan in plans.items():
        if pe_mandate and plan["minutes"]["PE"] < pe_mandate:
            flags.append(make_flag(
                "multiple", "specials_mandate_unmet", "critical",
                f"{homeroom} under the weekly PE minutes mandate",
                f"Homeroom {homeroom} received {plan['minutes']['PE']} minutes of PE; "
                f"{pe_mandate} are mandated.",
                legal_reference="Mandated Physical Education minutes requirement",
            ))
        for subject, missing in Counter(plan["queue"]).items():
            if subject == "PE":
                continue  # covered by the mandate flag above
            flags.append(make_flag(
                "multiple", "unscheduled_specials_period", "warning",
                f"{homeroom} short {missing} {subject} session(s)",
                f"Homeroom {homeroom} has {len(plan['blocks'])} Specials blocks per week; "
                f"they couldn't fit every target ({plan['needed']}) with the "
                f"teachers available.",
            ))
        if plan["unstaffed"]:
            flags.append(make_flag(
                "multiple", "specials_block_unstaffed", "warning",
                f"{homeroom}: {plan['unstaffed']} Specials block(s) with no teacher",
                f"No Specials teacher was free for {plan['unstaffed']} of homeroom "
                f"{homeroom}'s Specials blocks, so the homeroom teacher loses that prep.",
            ))

    return entries, flags


# ===============================================================
# FLEX (I-Block)
# ===============================================================

def get_flex_focus_area(student):
    """
    Returns a focus area for FLEX grouping. For enrichment students (no
    MTSS tier), still derive one from grade or homeroom so groups are
    descriptive and spreadable.
    """
    services_text = str(student.get("iep_services") or []).lower()

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


def pick_flex_teacher(
    focus_area: str,
    staff_members: list,
    load_fn=None,
    exclude: Optional[set] = None,
    own_grade: Optional[str] = None,
    teacher_grade: Optional[Dict[str, str]] = None,
) -> str:
    """
    Ranks candidates by role and load only -- the caller must still
    check real availability. Gen-ed teachers are limited to their own
    grade; their grade comes from their homeroom's students first
    (StaffMember.grade is often null), then StaffMember.grade.
    """
    exclude = exclude or set()
    teacher_grade = teacher_grade or {}

    def load(name):
        return load_fn(name) if load_fn else 0

    def best(candidates):
        candidates = [c for c in candidates if c not in exclude]
        return min(candidates, key=load) if candidates else ""

    def is_own_grade(staff):
        if own_grade is None:
            return True
        name = staff_full_name(staff)
        grade = teacher_grade.get(name) or normalize_grade(staff.get("grade"))
        return grade == own_grade

    def names(predicate):
        return [staff_full_name(s) for s in staff_members if staff_full_name(s) and predicate(s)]

    setss_qualified = names(lambda s: s.get("can_deliver_setss") or s.get("is_certified_sped"))
    gen_ed = names(lambda s: s.get("title") == "General Education Teacher" and is_own_grade(s))
    counselors = names(lambda s: s.get("title") in ("School Counselor", "School Psychologist", "Social Worker"))
    ict = names(lambda s: s.get("title") == "ICT Co-Teacher")
    paraprofessionals = names(lambda s: s.get("title") == "Paraprofessional")
    all_instructional = list(set(names(
        lambda s: s.get("title") not in ("Principal", "Assistant Principal", "General Education Teacher")
    )) | set(gen_ed))

    if focus_area in ("reading", "writing"):
        return (best(setss_qualified) or best(paraprofessionals) or best(gen_ed)
                or best(ict) or best(all_instructional))
    if focus_area == "math":
        return (best(paraprofessionals) or best(gen_ed) or best(setss_qualified)
                or best(ict) or best(all_instructional))
    if focus_area == "behavior":
        return best(counselors) or best(paraprofessionals) or best(all_instructional)
    return best(paraprofessionals) or best(gen_ed) or best(ict) or best(all_instructional)


def build_flex_groups(
    homeroom_info: Dict[str, Dict[str, Any]],
    staff_members: List[Dict[str, Any]],
    period_config: PeriodConfig,
    schedule_index: ScheduleIndex,
    teacher_grade: Dict[str, str],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    FLEX groups are built from each HOMEROOM's own roster inside that
    grade's FLEX-role block(s). A teacher is accepted only if they're
    free for the whole block on every day it runs. Students already
    pulled for a service keep that service; they join FLEX only for
    leftover pieces of at least min_flex_piece_minutes.
    """
    groups: List[Dict[str, Any]] = []
    entries: List[Dict[str, Any]] = []
    flags: List[Dict[str, Any]] = []
    flex_load: Counter = Counter()

    for homeroom, info in homeroom_info.items():
        grade = info["grade"]
        eligible = [
            s for s in info["roster"]
            if not (int(s.get("enl_minutes_required") or 0) > 0 and not s.get("mtss_tier"))
        ]
        flex_slots = [
            (day, block) for day in DAYS
            for block in period_config.blocks_for(grade, day)
            if period_config.role(block.subject) == ROLE_FLEX
        ]
        if not eligible or not flex_slots:
            continue

        buckets: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}
        for student in eligible:
            mtss_tier = student.get("mtss_tier")
            tier = mtss_tier if mtss_tier in ("tier_2", "tier_3") else "enrichment"
            buckets.setdefault((tier, get_flex_focus_area(student)), []).append(student)

        for (tier, focus_area), bucket_students in buckets.items():
            if tier == "enrichment":
                max_size = MAX_FLEX_GROUP_SIZE["enrichment"]
                base_name = f"FLEX Enrichment ({homeroom}) - {focus_area}"
                record_tier = "tier_2"
            else:
                max_size = MAX_FLEX_GROUP_SIZE.get(tier, 10)
                base_name = f"FLEX {tier.upper()} ({homeroom}) - {focus_area}"
                record_tier = tier

            for i in range(0, len(bucket_students), max_size):
                chunk = bucket_students[i:i + max_size]
                group_number = (i // max_size) + 1
                subject_name = f"{base_name} Group {group_number}"

                exhausted: Set[str] = set()
                teacher = ""
                while True:
                    candidate = pick_flex_teacher(
                        focus_area, staff_members, load_fn=lambda n: flex_load[n],
                        exclude=exhausted, own_grade=grade, teacher_grade=teacher_grade,
                    )
                    if not candidate:
                        break
                    if all(
                        schedule_index.teacher_conflict(
                            candidate, day, block.start, block.end, subject_name, ""
                        ) is None
                        for day, block in flex_slots
                    ):
                        teacher = candidate
                        break
                    exhausted.add(candidate)

                if not teacher:
                    critical = tier in ("tier_2", "tier_3")
                    flags.append(make_flag(
                        "multiple", "flex_group_understaffed",
                        "critical" if critical else "warning",
                        f"No available FLEX provider: {base_name} Group {group_number}",
                        f"{len(chunk)} student(s) in homeroom {homeroom} needed a {tier} "
                        f"FLEX group for {focus_area}, but no eligible staff member was "
                        f"free for the whole {flex_slots[0][1].subject} on every day. "
                        f"Add staff or reduce FLEX granularity.",
                        legal_reference=(
                            "MTSS / FLEX support requirement" if critical
                            else "School scheduling constraint"
                        ),
                        affected_period=f"{homeroom} {flex_slots[0][1].label}",
                    ))
                    continue

                flex_load[teacher] += 1
                for day, block in flex_slots:
                    schedule_index.reserve_teacher(
                        teacher, day, block.start, block.end, subject_name, "",
                        service_type="FLEX", block_subject=block.subject,
                        is_flex_period=True,
                    )
                    for student in chunk:
                        sid = student["student_id"]
                        for start, end in schedule_index.free_pieces(sid, day, block.start, block.end):
                            if end - start < period_config.min_flex_piece_minutes:
                                continue
                            entry = make_entry(
                                sid, day, start, end, period_config,
                                subject=subject_name, block_subject=block.subject,
                                teacher=teacher, room="", delivery=DELIVERY_CLASS,
                                service_type="FLEX", grade=grade, is_flex_period=True,
                            )
                            entries.append(entry)
                            schedule_index.add_entry(entry)

                    groups.append({
                        "name": subject_name,
                        "tier": record_tier,
                        "grade_group": grade,
                        "focus_area": focus_area,
                        "teacher": teacher,
                        "student_ids": [s["student_id"] for s in chunk],
                        "max_group_size": max_size,
                        "day_of_week": day,
                        "period": block.start,
                        "start_minute": block.start,
                        "end_minute": block.end,
                        "period_label": period_config.period_label(block.start),
                        "status": "active",
                        "group_number": group_number,
                    })

    return groups, entries, flags


# ===============================================================
# Fill the rest of each student's day from the master schedule
# ===============================================================

def fill_remaining_blocks(
    students: List[Dict[str, Any]],
    student_grade: Dict[str, str],
    student_homeroom: Dict[str, str],
    homeroom_info: Dict[str, Dict[str, Any]],
    period_config: PeriodConfig,
    schedule_index: ScheduleIndex,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    entries: List[Dict[str, Any]] = []
    flags: List[Dict[str, Any]] = []
    unsupervised_minutes: Counter = Counter()

    for student in students:
        sid = student["student_id"]
        grade = student_grade[sid]
        homeroom = student_homeroom.get(sid, "")
        info = homeroom_info.get(homeroom)
        teacher = info["teacher"] if info else ""

        if not homeroom:
            flags.append(make_flag(
                sid, "student_no_homeroom", "warning",
                f"{full_student_name(student)} has no homeroom",
                "Class blocks were scheduled without a teacher because the student "
                "isn't assigned to a homeroom.",
                legal_reference="Data integrity",
            ))

        for day in DAYS:
            for block in period_config.blocks_for(grade, day):
                role = period_config.role(block.subject)
                for start, end in schedule_index.free_pieces(sid, day, block.start, block.end):
                    subject, entry_teacher, room = block.subject, "", ""
                    if role in (ROLE_HOMEROOM, ROLE_FLEX):
                        room = homeroom
                        if teacher and schedule_index.teacher_conflict(
                            teacher, day, start, end, block.subject, homeroom, allow_partial=True
                        ) is None:
                            entry_teacher = teacher
                        elif teacher:
                            # e.g. the teacher is leading a FLEX group while an
                            # ENL-only student sits out I-Block
                            unsupervised_minutes[homeroom] += end - start
                    elif role == ROLE_SPECIALS:
                        subject, room = f"{block.subject} (unstaffed)", homeroom

                    entry = make_entry(
                        sid, day, start, end, period_config,
                        subject=subject, block_subject=block.subject,
                        teacher=entry_teacher, room=room, delivery=DELIVERY_CLASS,
                        service_type="General Ed", grade=grade,
                        is_flex_period=role == ROLE_FLEX,
                    )
                    entries.append(entry)
                    schedule_index.add_entry(entry)

    for homeroom, minutes in unsupervised_minutes.items():
        flags.append(make_flag(
            "multiple", "unsupervised_block_time", "warning",
            f"{homeroom}: {minutes} student-minutes/week with no adult assigned",
            f"Some homeroom {homeroom} students had class time while their teacher was "
            f"booked elsewhere (usually leading a FLEX group while students not in "
            f"FLEX, such as ENL-only students, sit out I-Block).",
        ))

    return entries, flags


# ===============================================================
# Staff schedules
# ===============================================================

def make_staff_entry(
    teacher: str,
    day: str,
    start: int,
    end: int,
    period_config: PeriodConfig,
    subject: str,
    block_subject: str,
    room: str,
    delivery: str,
    service_type: str,
    grade: Optional[str],
    student_ids: List[str],
    is_flex_period: bool = False,
) -> Dict[str, Any]:
    return {
        "teacher": teacher,
        "day_of_week": day,
        "period": start,
        "start_minute": start,
        "end_minute": end,
        "period_label": period_config.period_label(start),
        "time_range": format_range(start, end),
        "subject": subject,
        "block_subject": block_subject,
        "room": room,
        "is_pullout": delivery == DELIVERY_PULLOUT,
        "delivery": delivery,
        "service_type": service_type,
        "is_flex_period": is_flex_period,
        "grade": grade,
        "student_ids": student_ids,
        "student_count": len(student_ids),
    }


def build_staff_schedule_entries(
    schedule_index: ScheduleIndex,
    student_entries: List[Dict[str, Any]],
    homeroom_info: Dict[str, Dict[str, Any]],
    period_config: PeriodConfig,
) -> List[Dict[str, Any]]:
    """
    One row per teacher per class/session, from the teacher's side.

    Everything a teacher is booked for is already in the index, one
    interval per student (plus the student-less reservations). Intervals
    with the same (subject, room) label that overlap are one class -- a
    homeroom's ELA is split into pieces around pull-outs but is still
    one ELA block for the teacher. Back-to-back sessions (Speech at
    9:00 and again at 9:30) only touch, so they stay separate rows.

    Homeroom teachers also get rows for the rest of their class's day:
    Prep while a Specials teacher has the class, and the class's
    Lunch/Recess. Other staff only get what they were booked for --
    nothing in the data says when a provider takes lunch.
    """
    rows: List[Dict[str, Any]] = []

    def close(teacher, day, session):
        first = session[0]
        student_ids = list(dict.fromkeys(iv["student_id"] for iv in session if iv["student_id"]))
        grades = Counter(iv["grade"] for iv in session if iv["grade"])
        rows.append(make_staff_entry(
            teacher, day,
            min(iv["start"] for iv in session), max(iv["end"] for iv in session),
            period_config,
            subject=first["subject"], block_subject=first["block_subject"],
            room=first["room"], delivery=first["delivery"],
            service_type=first["service_type"],
            grade=grades.most_common(1)[0][0] if grades else None,
            student_ids=student_ids,
            is_flex_period=first["is_flex_period"],
        ))

    for (teacher, day), intervals in schedule_index.teacher_intervals.items():
        by_label: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}
        for iv in intervals:
            by_label.setdefault((iv["subject"], iv["room"]), []).append(iv)
        for items in by_label.values():
            items.sort(key=lambda iv: (iv["start"], iv["end"]))
            session: List[Dict[str, Any]] = []
            session_end = 0
            for iv in items:
                if session and iv["start"] >= session_end:
                    close(teacher, day, session)
                    session = []
                session_end = max(session_end, iv["end"]) if session else iv["end"]
                session.append(iv)
            if session:
                close(teacher, day, session)

    unstaffed_starts: Dict[Tuple[str, str], List[int]] = {}
    for entry in student_entries:
        if entry["subject"].endswith("(unstaffed)"):
            unstaffed_starts.setdefault(
                (entry["room"], entry["day_of_week"]), []
            ).append(entry["start_minute"])

    for homeroom, info in homeroom_info.items():
        teacher = info["teacher"]
        if not teacher:
            continue
        for day in DAYS:
            for block in period_config.blocks_for(info["grade"], day):
                role = period_config.role(block.subject)
                if role not in (ROLE_SPECIALS, ROLE_NONE):
                    continue
                unstaffed = role == ROLE_SPECIALS and any(
                    block.start <= s < block.end
                    for s in unstaffed_starts.get((homeroom, day), [])
                )
                for start, end in schedule_index.teacher_free_pieces(
                    teacher, day, block.start, block.end
                ):
                    if unstaffed:
                        # No Specials teacher took the class, so the
                        # homeroom teacher keeps it and loses the prep.
                        subject, delivery, service_type = (
                            f"{block.subject} (unstaffed)", DELIVERY_CLASS, "General Ed"
                        )
                    elif role == ROLE_SPECIALS:
                        subject, delivery, service_type = "Prep", DELIVERY_PREP, "Prep"
                    else:
                        subject, delivery, service_type = (
                            block.subject, DELIVERY_BREAK, "Non-instructional"
                        )
                    rows.append(make_staff_entry(
                        teacher, day, start, end, period_config,
                        subject=subject, block_subject=block.subject, room=homeroom,
                        delivery=delivery, service_type=service_type,
                        grade=info["grade"], student_ids=[],
                    ))

    rows.sort(key=lambda r: (r["teacher"], DAYS.index(r["day_of_week"]), r["start_minute"]))
    return rows


# ===============================================================
# Misc helpers
# ===============================================================

def priority_score(student: Dict[str, Any]) -> int:
    score = 0
    if student.get("has_iep"):
        score += 10000
    score += len(student.get("iep_services") or []) * 500
    score += int(student.get("enl_minutes_required") or 0)
    mtss_tier = student.get("mtss_tier")
    if mtss_tier == "tier_3":
        score += 2000
    elif mtss_tier == "tier_2":
        score += 1000
    return score


def add_to_staff_schedule(
    staff_schedule,
    teacher,
    day,
    period,
    student_id,
    student_name,
    subject,
    service_type,
    is_pullout,
    time_range="",
):
    if not teacher:
        return

    blocks = staff_schedule.setdefault(teacher, {}).setdefault(day, {}).setdefault(period, [])

    block = next(
        (b for b in blocks if b["subject"] == subject and b["service_type"] == service_type),
        None,
    )
    if block is None:
        block = {
            "subject": subject,
            "service_type": service_type,
            "is_pullout": is_pullout,
            "time_range": time_range,
            "students": [],
        }
        blocks.append(block)

    block["students"].append({"student_id": student_id, "student_name": student_name})


# ===============================================================
# Main entry point
# ===============================================================

def schedule_iep_services_first(
    students: List[Dict[str, Any]],
    staff_members: List[Dict[str, Any]] | None = None,
    school_year: str = "2026-2027",
    period_config: Optional[PeriodConfig] = None,
    progress_callback=None,  # optional callable(stage_index: int, message: str | None = None)
) -> Dict[str, Any]:
    """
    Main scheduler. See scheduling_core.py for PeriodConfig/constants
    and compliance.py for post-build validation.
    """
    staff_members = staff_members or []
    period_config = period_config or PeriodConfig()

    logger.info(
        "Scheduler start: grades=%s max_pullouts_per_day=%s min_gap_minutes=%s "
        "pullout_blocks=%s pushin_blocks=%s",
        period_config.grades,
        period_config.max_pullouts_per_day,
        period_config.min_gap_minutes,
        sorted(s for s, p in period_config.block_policies.items() if p["allow_pullout"]),
        sorted(s for s, p in period_config.block_policies.items() if p["allow_pushin"]),
    )

    schedule_index = ScheduleIndex()
    all_entries: List[Dict[str, Any]] = []
    compliance_flags: List[Dict[str, Any]] = []

    ranked_students = sorted(students, key=priority_score, reverse=True)
    students_by_id = {s["student_id"]: s for s in students if s.get("student_id")}

    # ---------------------------------------------------------
    # 0. Validate grades, resolve homerooms, reserve homeroom teachers.
    #    A student whose grade has no master schedule is flagged and
    #    left unscheduled -- no fallback grade.
    # ---------------------------------------------------------
    student_grade: Dict[str, str] = {}
    student_homeroom: Dict[str, str] = {}
    schedulable: List[Dict[str, Any]] = []

    for student in ranked_students:
        sid = student.get("student_id")
        if not sid:
            continue
        grade = period_config.grade_for_student(student)
        if grade is None:
            compliance_flags.append(make_flag(
                sid, "no_master_schedule_for_grade", "critical",
                f"{full_student_name(student)} was not scheduled",
                f"Grade '{student.get('grade')}' has no blocks in the master schedule "
                f"(configured grades: {period_config.grades}). Add that grade's blocks "
                f"or fix the student's grade.",
                legal_reference="Data integrity",
            ))
            continue
        student_grade[sid] = grade
        student_homeroom[sid] = str(student.get("homeroom") or "").strip()
        schedulable.append(student)

    homeroom_info, homeroom_flags = resolve_homerooms(schedulable, student_grade, staff_members)
    compliance_flags.extend(homeroom_flags)
    reserve_homeroom_teachers(homeroom_info, period_config, schedule_index)

    teacher_grade = {info["teacher"]: info["grade"] for info in homeroom_info.values() if info["teacher"]}

    # ---------------------------------------------------------
    # 1. Mandated services -- first claim on every slot.
    # ---------------------------------------------------------
    if progress_callback:
        progress_callback(0, "Placing mandated IEP/ENL/related services")

    service_entries, service_flags, placement_report = place_mandated_services(
        schedulable, student_grade, student_homeroom, staff_members,
        period_config, schedule_index,
    )
    all_entries.extend(service_entries)
    compliance_flags.extend(service_flags)

    # ---------------------------------------------------------
    # 2. Specials (the homeroom teacher's prep)
    # ---------------------------------------------------------
    if progress_callback:
        progress_callback(1, "Assigning Specials teachers (PE/Music/Art)")

    specials_entries, specials_flags = build_specials_schedule(
        homeroom_info, staff_members, period_config, schedule_index,
    )
    all_entries.extend(specials_entries)
    compliance_flags.extend(specials_flags)

    # ---------------------------------------------------------
    # 3. FLEX groups in the I-Block
    # ---------------------------------------------------------
    if progress_callback:
        progress_callback(2, "Building FLEX groups")

    flex_groups, flex_entries, flex_flags = build_flex_groups(
        homeroom_info, staff_members, period_config, schedule_index, teacher_grade,
    )
    all_entries.extend(flex_entries)
    compliance_flags.extend(flex_flags)

    student_flex_group_rows = [
        {
            "student_id": student_id,
            "group_name": group["name"],
            "tier": group["tier"],
            "grade_group": group["grade_group"],
            "focus_area": group["focus_area"],
            "teacher": group["teacher"],
            "day_of_week": group["day_of_week"],
            "period": group["period"],
            "period_label": group.get("period_label", ""),
        }
        for group in flex_groups
        for student_id in group["student_ids"]
    ]

    # ---------------------------------------------------------
    # 4. Everything else in each student's day
    # ---------------------------------------------------------
    if progress_callback:
        progress_callback(3, "Filling homeroom blocks from the master schedule")

    class_entries, class_flags = fill_remaining_blocks(
        schedulable, student_grade, student_homeroom, homeroom_info,
        period_config, schedule_index,
    )
    all_entries.extend(class_entries)
    compliance_flags.extend(class_flags)

    all_entries.sort(key=lambda e: (e["student_id"], DAYS.index(e["day_of_week"]), e["start_minute"]))

    staff_schedule: Dict[str, Any] = {}
    for entry in all_entries:
        add_to_staff_schedule(
            staff_schedule=staff_schedule,
            teacher=entry["teacher"],
            day=entry["day_of_week"],
            period=entry["period"],
            student_id=entry["student_id"],
            student_name=full_student_name(students_by_id.get(entry["student_id"], {})),
            subject=entry["subject"],
            service_type=entry["service_type"],
            is_pullout=entry["is_pullout"],
            time_range=entry["time_range"],
        )

    # ---------------------------------------------------------
    # 5. Staff schedules (the rows that get saved per teacher)
    # ---------------------------------------------------------
    staff_schedule_entries = build_staff_schedule_entries(
        schedule_index, all_entries, homeroom_info, period_config,
    )

    # ---------------------------------------------------------
    # 6. Validate
    # ---------------------------------------------------------
    if progress_callback:
        progress_callback(4, "Running compliance validation")

    compliance_flags.extend(
        run_all_compliance_checks(
            entries=all_entries,
            students_by_id=students_by_id,
            period_config=period_config,
            students=students,
            staff_members=staff_members,
        )
    )

    # ---------------------------------------------------------
    # 7. ScheduleProposal records
    # ---------------------------------------------------------
    if progress_callback:
        progress_callback(5, "Building schedule proposals")

    entries_by_student: Dict[str, List[Dict[str, Any]]] = {}
    for entry in all_entries:
        entries_by_student.setdefault(entry["student_id"], []).append(entry)

    critical_by_student = Counter(
        f.get("student_id") for f in compliance_flags if f.get("severity") == "critical"
    )

    schedule_proposals: List[Dict[str, Any]] = []
    for student in ranked_students:
        student_id = student.get("student_id")
        if not student_id:
            continue
        critical_count = critical_by_student.get(student_id, 0)
        schedule_proposals.append({
            "student_id": student_id,
            "student_name": full_student_name(student),
            "school_year": school_year,
            "proposed_by": "scheduler-engine",
            "proposed_by_name": "Scheduler Engine",
            "entries": [
                {
                    "day_of_week": e["day_of_week"],
                    "period": e["period"],
                    "start_minute": e["start_minute"],
                    "end_minute": e["end_minute"],
                    "period_label": e["period_label"],
                    "time_range": e["time_range"],
                    "subject": e["subject"],
                    "block_subject": e["block_subject"],
                    "teacher": e["teacher"],
                    "service_type": e["service_type"],
                    "delivery": e["delivery"],
                    "is_pullout": e["is_pullout"],
                    "is_flex_period": e["is_flex_period"],
                }
                for e in entries_by_student.get(student_id, [])
            ],
            "compliance_check_passed": critical_count == 0,
            "open_critical_flags": critical_count,
            "status": "draft",
        })

    # ---------------------------------------------------------
    # 8. Return everything to the API layer
    # ---------------------------------------------------------
    sessions_short = sum(
        r["sessions_needed"] - r["sessions_scheduled"] for r in placement_report
    )
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
                "grade": student_grade.get(student.get("student_id")),
                # kept for the frontend; grades no longer share groups
                "grade_group": student_grade.get(student.get("student_id")),
            }
            for student in ranked_students
        ],
        "schedule_entries": all_entries,
        "schedule_proposals": schedule_proposals,
        "compliance_flags": compliance_flags,
        "flex_groups": flex_groups,
        "flex_group_students": student_flex_group_rows,
        "staff_schedule": staff_schedule,
        "staff_schedule_entries": staff_schedule_entries,
        "service_placement_report": placement_report,
        "period_config": period_config.to_dict(),
        "summary": {
            "schedule_entries_created": len(all_entries),
            "schedule_proposals_created": len(schedule_proposals),
            "compliance_flags_created": len(compliance_flags),
            "flex_groups_created": len(flex_groups),
            "flex_group_students_created": len(student_flex_group_rows),
            "staff_members_scheduled": len(staff_schedule),
            "staff_schedule_entries_created": len(staff_schedule_entries),
            "service_sessions_short": sessions_short,
        },
    }