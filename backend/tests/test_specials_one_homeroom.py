"""
A Specials teacher teaches one homeroom at a time: the scheduler must
never put two homerooms in the same Specials period with one teacher,
and the compliance check must catch it if a schedule ever does.
Pure Python -- no database needed.
"""
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from compliance import validate_specials_one_homeroom  # noqa: E402
from scheduler import ScheduleIndex, build_specials_schedule  # noqa: E402
from scheduling_core import DAYS, ROLE_SPECIALS, PeriodConfig  # noqa: E402


def _homerooms(grade, names, size=20):
    return {
        hr: {
            "grade": grade,
            "teacher": "",
            "roster": [{"student_id": f"{hr}-{i}", "homeroom": hr} for i in range(size)],
        }
        for hr in names
    }


def _specials_block(period_config, grade):
    return next(
        b for d in DAYS for b in period_config.blocks_for(grade, d)
        if period_config.role(b.subject) == ROLE_SPECIALS
    )


def test_one_teacher_never_takes_two_homerooms_in_the_same_period():
    pc = PeriodConfig()
    grade = pc.grades[0]
    # Three homerooms share the same Specials block, and there's only
    # one PE teacher and one Music teacher -- not enough for everyone.
    staff = [
        {"first_name": "Pat", "last_name": "Gym", "title": "PE Teacher"},
        {"first_name": "Mel", "last_name": "Odie", "title": "Music Teacher"},
    ]
    info = _homerooms(grade, ["2A", "2B", "2C"])
    entries, flags = build_specials_schedule(info, staff, pc, ScheduleIndex())

    homeroom_of = {s["student_id"]: hr for hr, h in info.items() for s in h["roster"]}
    classes = defaultdict(set)
    for e in entries:
        classes[(e["teacher"], e["day_of_week"], e["start_minute"])].add(homeroom_of[e["student_id"]])
    assert classes, "expected some Specials to be scheduled"
    for (teacher, day, start), homerooms in classes.items():
        assert len(homerooms) == 1, f"{teacher} has {sorted(homerooms)} together on {day} at {start}"

    # Nobody was combined; the homeroom left without a teacher is flagged instead.
    flag_types = {f["flag_type"] for f in flags}
    assert "specials_classes_combined" not in flag_types
    assert "specials_block_unstaffed" in flag_types
    assert validate_specials_one_homeroom(
        entries, {sid: {"homeroom": hr} for sid, hr in homeroom_of.items()}, pc,
    ) == []


def test_compliance_flags_two_homerooms_with_one_specials_teacher():
    pc = PeriodConfig()
    grade = pc.grades[0]
    block = _specials_block(pc, grade)

    def entry(student_id, label):
        return {
            "student_id": student_id, "teacher": "Pat Gym", "day_of_week": "A",
            "start_minute": block.start, "end_minute": block.end,
            "subject": f"PE - {label}", "room": label, "block_subject": block.subject,
            "service_type": "General Ed", "delivery": "class",
        }

    students = {"s1": {"homeroom": "2A"}, "s2": {"homeroom": "2B"}}
    combined = [entry("s1", "2A"), entry("s2", "2A")]  # 2B joined 2A's class
    flags = validate_specials_one_homeroom(combined, students, pc)
    assert [f["flag_type"] for f in flags] == ["specials_homerooms_combined"]
    assert flags[0]["severity"] == "critical"
    assert "2A" in flags[0]["description"] and "2B" in flags[0]["description"]

    # Same teacher, different days or different periods is fine.
    later = dict(entry("s2", "2B"), day_of_week="B")
    assert validate_specials_one_homeroom([entry("s1", "2A"), later], students, pc) == []


def test_old_saved_config_with_merge_option_still_loads():
    payload = PeriodConfig().to_config_payload()
    payload["pullout_constraints"]["allow_specials_merge"] = True
    loaded = PeriodConfig.from_config(payload)
    assert not hasattr(loaded, "allow_specials_merge")
