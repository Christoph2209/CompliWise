import { useState, useRef, useEffect, useMemo } from "react";
import {
  startScheduleGeneration,
  getScheduleGenerationStatus,
  getScheduleConfigDefaults,
  type ScheduleJobStatus,
} from "../api/schedule";
import "./GenerateScheduleModal.css";

// ---------- Types ----------
// Mirrors PeriodConfig.from_config() in scheduling_core.py.

export const WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"] as const;
export type Weekday = (typeof WEEKDAYS)[number];

export type BlockRole = "homeroom" | "flex" | "specials" | "none";

export interface BlockDefinition {
  subject: string;
  start_time: string; // "HH:MM" 24hr
  end_time: string;   // "HH:MM" 24hr
  days: Weekday[];
}

export interface GradeSchedule {
  grade: string;
  blocks: BlockDefinition[];
}

export interface BlockPolicy {
  subject: string;
  role: BlockRole;
  allow_pullout: boolean;
  allow_pushin: boolean;
  pullout_score: number; // higher = better place to pull a student from
}

export interface PulloutConstraints {
  max_pullouts_per_day: number;
  min_gap_minutes: number;
  allow_specials_merge: boolean; // combine two homerooms into one shared specials session
}

export interface SpecialsRequirement {
  subject: string; // e.g. "PE", "Music", "Art"
  sessions_per_week: number;
}

export interface ScheduleGenerationConfig {
  grade_schedules: GradeSchedule[];
  block_policies: BlockPolicy[];
  pullout_constraints: PulloutConstraints;
  specials_requirements: SpecialsRequirement[];
}

export interface ScheduleConfigDefaults {
  source: "defaults" | "last_run";
  run_id?: string;
  warning?: string;
  config: ScheduleGenerationConfig;
}

// Editor copies carry an id for React keys; ids are stripped on submit.
type EditableBlock = BlockDefinition & { id: string };
type EditableGrade = { grade: string; blocks: EditableBlock[] };
type EditableSpecial = SpecialsRequirement & { id: string };

interface GenerateScheduleModalProps {
  onClose: () => void;
  onGenerated: () => void | Promise<void>;
}

// ---------- Constants ----------

const DAY_SHORT: Record<Weekday, string> = {
  Monday: "M",
  Tuesday: "T",
  Wednesday: "W",
  Thursday: "Th",
  Friday: "F",
};

const ROLE_LABELS: Record<BlockRole, string> = {
  homeroom: "Homeroom teacher teaches it",
  flex: "Intervention / FLEX groups",
  specials: "Specials teacher (homeroom prep)",
  none: "No teacher (lunch, recess)",
};

// Mirrors SPECIALS_MANDATED_MINUTES_PER_WEEK -- these session counts are
// derived from a legal minutes mandate, so they aren't editable here.
const MANDATED_SPECIALS: Record<string, number> = { PE: 90 };

// Same colors as the paper master schedule, so the preview can be
// checked against it at a glance.
const SUBJECT_COLORS: Record<string, string> = {
  ELA: "#ffffff",
  Math: "#ffffff",
  "SS/Sci": "#ffffff",
  "I-Block": "#d4d4d8",
  Specials: "#fde047",
  Lunch: "#f9a8d4",
  Recess: "#db2777",
};

function subjectColor(subject: string): string {
  if (SUBJECT_COLORS[subject]) return SUBJECT_COLORS[subject];
  let hash = 0;
  for (const ch of subject) hash = (hash * 31 + ch.charCodeAt(0)) % 360;
  return `hsl(${hash} 65% 85%)`;
}

function subjectTextColor(subject: string): string {
  return subject === "Recess" ? "#ffffff" : "#1f2937";
}

let idCounter = 0;
function nextId(prefix: string) {
  idCounter += 1;
  return `${prefix}_${Date.now()}_${idCounter}`;
}

function toMinutes(hhmm: string): number {
  const [h, m] = hhmm.split(":").map(Number);
  return h * 60 + m;
}

function toHHMM(minutes: number): string {
  const clamped = Math.max(0, Math.min(minutes, 23 * 60 + 59));
  const h = Math.floor(clamped / 60);
  const m = clamped % 60;
  return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}`;
}

function formatClock(hhmm: string): string {
  const total = toMinutes(hhmm);
  const h = Math.floor(total / 60);
  const m = total % 60;
  return `${h % 12 || 12}:${String(m).padStart(2, "0")}`;
}

/** First overlap inside one grade's day, as a message -- or null. */
function findOverlap(grade: EditableGrade): string | null {
  for (const day of WEEKDAYS) {
    const todays = grade.blocks
      .filter((b) => b.days.includes(day) && b.start_time && b.end_time)
      .sort((a, b) => toMinutes(a.start_time) - toMinutes(b.start_time));
    for (let i = 1; i < todays.length; i += 1) {
      const prev = todays[i - 1];
      const curr = todays[i];
      if (toMinutes(curr.start_time) < toMinutes(prev.end_time)) {
        return (
          `Grade ${grade.grade} on ${day}: ${prev.subject} ` +
          `(${formatClock(prev.start_time)}-${formatClock(prev.end_time)}) overlaps ` +
          `${curr.subject} (${formatClock(curr.start_time)}-${formatClock(curr.end_time)}).`
        );
      }
    }
  }
  return null;
}

type Tab = "master" | "rules" | "specials";

const POLL_INTERVAL_MS = 750;

// ---------- Timeline preview ----------

function MasterScheduleTimeline({
  grades,
  selectedGrade,
  onSelect,
}: {
  grades: EditableGrade[];
  selectedGrade: string;
  onSelect: (grade: string) => void;
}) {
  const valid = grades.flatMap((g) =>
    g.blocks.filter((b) => b.start_time && b.end_time && b.start_time < b.end_time)
  );
  if (valid.length === 0) return null;

  const dayStart = Math.min(...valid.map((b) => toMinutes(b.start_time)));
  const dayEnd = Math.max(...valid.map((b) => toMinutes(b.end_time)));
  const pxPerMinute = 1.1;
  const height = (dayEnd - dayStart) * pxPerMinute;

  return (
    <div className="gsm-timeline" aria-label="Master schedule preview">
      {grades.map((g) => (
        <button
          type="button"
          key={g.grade}
          className={`gsm-timeline-col${g.grade === selectedGrade ? " active" : ""}`}
          onClick={() => onSelect(g.grade)}
          aria-label={`Edit grade ${g.grade}`}
        >
          <span className="gsm-timeline-head">{g.grade}</span>
          <span className="gsm-timeline-track" style={{ height }}>
            {g.blocks
              .filter((b) => b.start_time && b.end_time && b.start_time < b.end_time)
              .map((b) => {
                const top = (toMinutes(b.start_time) - dayStart) * pxPerMinute;
                const blockHeight = (toMinutes(b.end_time) - toMinutes(b.start_time)) * pxPerMinute;
                const partWeek = b.days.length < WEEKDAYS.length;
                return (
                  <span
                    key={b.id}
                    className={`gsm-timeline-block${partWeek ? " part-week" : ""}`}
                    style={{
                      top,
                      height: blockHeight,
                      background: subjectColor(b.subject),
                      color: subjectTextColor(b.subject),
                    }}
                    title={
                      `${b.subject} ${formatClock(b.start_time)}-${formatClock(b.end_time)}` +
                      (partWeek ? ` (${b.days.map((d) => DAY_SHORT[d]).join(" ")})` : "")
                    }
                  >
                    {blockHeight >= 13 ? b.subject : ""}
                  </span>
                );
              })}
          </span>
        </button>
      ))}
    </div>
  );
}

// ---------- Modal ----------

export default function GenerateScheduleModal({ onClose, onGenerated }: GenerateScheduleModalProps) {
  const [tab, setTab] = useState<Tab>("master");

  const [loadState, setLoadState] = useState<"loading" | "ready" | "error">("loading");
  const [loadNote, setLoadNote] = useState<string | null>(null);

  const [grades, setGrades] = useState<EditableGrade[]>([]);
  const [selectedGrade, setSelectedGrade] = useState<string>("");
  const [newGradeName, setNewGradeName] = useState("");
  const [policies, setPolicies] = useState<BlockPolicy[]>([]);
  const [newSubjectName, setNewSubjectName] = useState("");
  const [pulloutConstraints, setPulloutConstraints] = useState<PulloutConstraints>({
    max_pullouts_per_day: 2,
    min_gap_minutes: 0,
    allow_specials_merge: true,
  });
  const [specials, setSpecials] = useState<EditableSpecial[]>([]);

  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [jobStatus, setJobStatus] = useState<ScheduleJobStatus | null>(null);

  const pollRef = useRef<number | null>(null);

  const [displayedPercent, setDisplayedPercent] = useState(0);
  const creepRef = useRef<number | null>(null);

  const subjectNames = useMemo(() => policies.map((p) => p.subject), [policies]);

  // Shortest Specials block across grades -- what a mandated subject's
  // session count is computed from (same rule as the scheduler).
  const shortestSpecialsBlock = useMemo(() => {
    const specialsSubjects = new Set(policies.filter((p) => p.role === "specials").map((p) => p.subject));
    const lengths = grades.flatMap((g) =>
      g.blocks
        .filter((b) => specialsSubjects.has(b.subject) && b.start_time < b.end_time)
        .map((b) => toMinutes(b.end_time) - toMinutes(b.start_time))
    );
    return lengths.length ? Math.min(...lengths) : null;
  }, [grades, policies]);
  const currentGrade = grades.find((g) => g.grade === selectedGrade) ?? null;

  // ---------- Load the last run's master schedule (or the defaults) ----------

  async function loadConfig() {
    setLoadState("loading");
    setError(null);
    try {
      const defaults = await getScheduleConfigDefaults();
      const cfg = defaults.config;
      const loadedGrades = cfg.grade_schedules.map((g) => ({
        grade: g.grade,
        blocks: g.blocks.map((b) => ({ ...b, id: nextId("block") })),
      }));
      setGrades(loadedGrades);
      setSelectedGrade(loadedGrades[0]?.grade ?? "");
      setPolicies(cfg.block_policies);
      setPulloutConstraints(cfg.pullout_constraints);
      setSpecials(cfg.specials_requirements.map((s) => ({ ...s, id: nextId("special") })));
      setLoadNote(
        defaults.warning ??
          (defaults.source === "last_run"
            ? "Loaded from your last generated schedule."
            : "Starting from the built-in master schedule. Check it against your bell schedule before generating.")
      );
      setLoadState("ready");
    } catch (err) {
      console.error("Error loading schedule configuration:", err);
      setLoadState("error");
    }
  }

  useEffect(() => {
    loadConfig();
  }, []);

  // ---------- Progress bar animation ----------

  useEffect(() => {
    if (!jobStatus) return;

    const target = jobStatus.percent;

    if (creepRef.current !== null) {
      window.clearInterval(creepRef.current);
      creepRef.current = null;
    }

    // Nudge toward the real target; the CSS transition renders this
    // as a smooth sweep rather than an instant snap.
    const nudge = window.setTimeout(() => setDisplayedPercent(target), 20);

    // While the job is still in flight, creep the displayed percent
    // forward a little past the last known target -- capped well short
    // of 100 so it never claims completion before the server does.
    if (jobStatus.status === "running" || jobStatus.status === "queued") {
      const creepCap = Math.min(target + 8, 99);
      creepRef.current = window.setInterval(() => {
        setDisplayedPercent((current) => (current < creepCap ? current + 1 : current));
      }, 400);
    }

    return () => {
      window.clearTimeout(nudge);
      if (creepRef.current !== null) {
        window.clearInterval(creepRef.current);
        creepRef.current = null;
      }
    };
  }, [jobStatus?.percent, jobStatus?.status]);

  // Snap cleanly to 100 on completion, clearing any lingering creep.
  useEffect(() => {
    if (jobStatus?.status === "complete") {
      if (creepRef.current !== null) {
        window.clearInterval(creepRef.current);
        creepRef.current = null;
      }
      setDisplayedPercent(100);
    }
  }, [jobStatus?.status]);

  // Make sure a stray interval never survives the component unmounting.
  useEffect(() => {
    return () => {
      if (pollRef.current !== null) {
        window.clearInterval(pollRef.current);
      }
      if (creepRef.current !== null) {
        window.clearInterval(creepRef.current);
      }
    };
  }, []);

  function stopPolling() {
    if (pollRef.current !== null) {
      window.clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }

  // ---------- Master schedule handlers ----------

  function updateGradeBlocks(grade: string, update: (blocks: EditableBlock[]) => EditableBlock[]) {
    setGrades((prev) => prev.map((g) => (g.grade === grade ? { ...g, blocks: update(g.blocks) } : g)));
  }

  function updateBlock(grade: string, blockId: string, patch: Partial<BlockDefinition>) {
    updateGradeBlocks(grade, (blocks) => blocks.map((b) => (b.id === blockId ? { ...b, ...patch } : b)));
  }

  function toggleBlockDay(grade: string, blockId: string, day: Weekday) {
    updateGradeBlocks(grade, (blocks) =>
      blocks.map((b) => {
        if (b.id !== blockId) return b;
        const days = b.days.includes(day) ? b.days.filter((d) => d !== day) : [...b.days, day];
        return { ...b, days: WEEKDAYS.filter((d) => days.includes(d)) };
      })
    );
  }

  function addBlock(grade: string) {
    updateGradeBlocks(grade, (blocks) => {
      const lastEnd = blocks.reduce(
        (latest, b) => (b.end_time && b.end_time > latest ? b.end_time : latest),
        "08:00"
      );
      return [
        ...blocks,
        {
          id: nextId("block"),
          subject: subjectNames.includes("ELA") ? "ELA" : subjectNames[0] ?? "",
          start_time: lastEnd,
          end_time: toHHMM(toMinutes(lastEnd) + 45),
          days: [...WEEKDAYS],
        },
      ];
    });
  }

  function removeBlock(grade: string, blockId: string) {
    updateGradeBlocks(grade, (blocks) => blocks.filter((b) => b.id !== blockId));
  }

  function sortBlocks(grade: string) {
    updateGradeBlocks(grade, (blocks) =>
      [...blocks].sort((a, b) => a.start_time.localeCompare(b.start_time))
    );
  }

  function addGrade() {
    const name = newGradeName.trim().toUpperCase();
    if (!name) return;
    if (grades.some((g) => g.grade === name)) {
      setError(`Grade ${name} is already in the master schedule.`);
      return;
    }
    setError(null);
    setGrades((prev) => [...prev, { grade: name, blocks: [] }]);
    setSelectedGrade(name);
    setNewGradeName("");
  }

  function removeGrade(grade: string) {
    const remaining = grades.filter((g) => g.grade !== grade);
    setGrades(remaining);
    if (selectedGrade === grade) setSelectedGrade(remaining[0]?.grade ?? "");
  }

  function copyBlocks(fromGrade: string, toGrade: string) {
    const source = grades.find((g) => g.grade === fromGrade);
    if (!source || !toGrade) return;
    updateGradeBlocks(toGrade, () => source.blocks.map((b) => ({ ...b, id: nextId("block") })));
    setSelectedGrade(toGrade);
  }

  // ---------- Rule (block policy) handlers ----------

  function updatePolicy(subject: string, patch: Partial<BlockPolicy>) {
    setPolicies((prev) => prev.map((p) => (p.subject === subject ? { ...p, ...patch } : p)));
  }

  function addPolicy() {
    const name = newSubjectName.trim();
    if (!name) return;
    if (policies.some((p) => p.subject.toLowerCase() === name.toLowerCase())) {
      setError(`"${name}" is already a block subject.`);
      return;
    }
    setError(null);
    setPolicies((prev) => [
      ...prev,
      { subject: name, role: "homeroom", allow_pullout: false, allow_pushin: false, pullout_score: 0 },
    ]);
    setNewSubjectName("");
  }

  function removePolicy(subject: string) {
    const usedBy = grades.filter((g) => g.blocks.some((b) => b.subject === subject)).map((g) => g.grade);
    if (usedBy.length > 0) {
      setError(`"${subject}" is still used in grade(s) ${usedBy.join(", ")}. Change those blocks first.`);
      return;
    }
    setError(null);
    setPolicies((prev) => prev.filter((p) => p.subject !== subject));
  }

  // ---------- Specials handlers ----------

  function updateSpecial(id: string, field: keyof SpecialsRequirement, value: string | number) {
    setSpecials((prev) => prev.map((s) => (s.id === id ? { ...s, [field]: value } : s)));
  }

  function addSpecial() {
    setSpecials((prev) => [...prev, { id: nextId("special"), subject: "", sessions_per_week: 1 }]);
  }

  function removeSpecial(id: string) {
    setSpecials((prev) => prev.filter((s) => s.id !== id));
  }

  // ---------- Validation ----------

  function validate(): string | null {
    if (grades.length === 0) return "Add at least one grade to the master schedule.";
    for (const g of grades) {
      if (g.blocks.length === 0) return `Grade ${g.grade} has no blocks.`;
      for (const b of g.blocks) {
        if (!subjectNames.includes(b.subject)) {
          return `Grade ${g.grade}: "${b.subject || "(blank)"}" isn't a block subject. Pick one, or add it under Pull-out & push-in rules.`;
        }
        if (!b.start_time || !b.end_time) return `Grade ${g.grade}: a ${b.subject} block is missing a time.`;
        if (b.start_time >= b.end_time) {
          return `Grade ${g.grade}: ${b.subject} at ${formatClock(b.start_time)} must end after it starts.`;
        }
        if (b.days.length === 0) return `Grade ${g.grade}: a ${b.subject} block has no days selected.`;
      }
      const overlap = findOverlap(g);
      if (overlap) return overlap;
    }
    if (pulloutConstraints.max_pullouts_per_day < 1) return "Max pullouts per day must be at least 1.";
    if (pulloutConstraints.min_gap_minutes < 0) return "Minimum gap can't be negative.";
    for (const p of policies) {
      if (!Number.isInteger(p.pullout_score)) return `${p.subject}: pull-out preference must be a whole number.`;
    }
    for (const s of specials) {
      if (!s.subject.trim()) return "Every specials row needs a subject name.";
      if (s.sessions_per_week < 1) return `${s.subject}: sessions per week must be at least 1.`;
    }
    return null;
  }

  // ---------- Submit + poll ----------

  async function handleSubmit() {
    const validationError = validate();
    if (validationError) {
      setError(validationError);
      return;
    }
    setError(null);
    setIsSubmitting(true);
    setJobStatus({
      status: "queued",
      current_stage: -1,
      stage_name: null,
      percent: 0,
    });
    setDisplayedPercent(0);

    const config: ScheduleGenerationConfig = {
      grade_schedules: grades.map((g) => ({
        grade: g.grade,
        blocks: g.blocks.map(({ id: _id, ...block }) => block),
      })),
      block_policies: policies,
      pullout_constraints: pulloutConstraints,
      specials_requirements: specials.map(({ id: _id, ...s }) => s),
    };

    try {
      const { job_id } = await startScheduleGeneration(config);

      pollRef.current = window.setInterval(async () => {
        try {
          const status = await getScheduleGenerationStatus(job_id);
          setJobStatus(status);

          if (status.status === "complete") {
            stopPolling();
            await onGenerated();
            onClose();
          } else if (status.status === "error") {
            stopPolling();
            setError(status.error || "Schedule generation failed. Check the console for details.");
            setIsSubmitting(false);
          }
        } catch (pollErr) {
          console.error("Error polling schedule generation status:", pollErr);
          stopPolling();
          setError("Lost connection while checking generation progress.");
          setIsSubmitting(false);
        }
      }, POLL_INTERVAL_MS);
    } catch (err) {
      console.error("Error starting schedule generation:", err);
      setError("Schedule generation didn't start. Check the console for details.");
      setIsSubmitting(false);
    }
  }

  // ---------- Render ----------

  return (
    <div className="gsm-overlay" onClick={onClose}>
      <div className="gsm-modal gsm-modal-wide" onClick={(e) => e.stopPropagation()}>
        <div className="gsm-header">
          <h2>Generate Schedule</h2>
          <button className="gsm-close" onClick={onClose} aria-label="Close">
            ✕
          </button>
        </div>

        <div className="gsm-tabs">
          <button className={tab === "master" ? "active" : ""} onClick={() => setTab("master")}>
            Master Schedule
          </button>
          <button className={tab === "rules" ? "active" : ""} onClick={() => setTab("rules")}>
            Pull-out &amp; Push-in Rules
          </button>
          <button className={tab === "specials" ? "active" : ""} onClick={() => setTab("specials")}>
            Specials
          </button>
        </div>

        <div className="gsm-body">
          {loadState === "loading" && <p className="gsm-hint">Loading the master schedule…</p>}

          {loadState === "error" && (
            <div className="gsm-section">
              <p className="gsm-hint">
                The master schedule couldn't be loaded from the server. Check that the backend is
                running, then try again.
              </p>
              <button className="gsm-add-btn" onClick={loadConfig}>
                Try again
              </button>
            </div>
          )}

          {loadState === "ready" && tab === "master" && (
            <div className="gsm-section">
              {loadNote && <p className="gsm-notice">{loadNote}</p>}
              <p className="gsm-hint">
                Enter each grade's day exactly as it appears on the master schedule. The scheduler
                pulls students out and pushes providers in only inside these blocks, following the
                rules on the next tab.
              </p>

              <div className="gsm-master-layout">
                <div className="gsm-master-editor">
                  <div className="gsm-grade-chips" role="tablist" aria-label="Grades">
                    {grades.map((g) => (
                      <button
                        key={g.grade}
                        role="tab"
                        aria-selected={g.grade === selectedGrade}
                        className={`gsm-grade-chip${g.grade === selectedGrade ? " active" : ""}`}
                        onClick={() => setSelectedGrade(g.grade)}
                      >
                        {g.grade}
                      </button>
                    ))}
                    <span className="gsm-add-grade">
                      <input
                        type="text"
                        placeholder="New grade"
                        value={newGradeName}
                        maxLength={12}
                        onChange={(e) => setNewGradeName(e.target.value)}
                        onKeyDown={(e) => e.key === "Enter" && addGrade()}
                        aria-label="New grade name"
                      />
                      <button className="gsm-add-btn" onClick={addGrade}>
                        Add grade
                      </button>
                    </span>
                  </div>

                  {currentGrade && (
                    <>
                      <div className="gsm-block-list">
                        <div className="gsm-block-row gsm-block-row-header">
                          <span>Subject</span>
                          <span>Start</span>
                          <span>End</span>
                          <span>Days</span>
                          <span></span>
                        </div>
                        {currentGrade.blocks.map((b) => (
                          <div className="gsm-block-row" key={b.id}>
                            <select
                              value={b.subject}
                              onChange={(e) => updateBlock(currentGrade.grade, b.id, { subject: e.target.value })}
                              aria-label="Block subject"
                            >
                              {!subjectNames.includes(b.subject) && <option value={b.subject}>{b.subject || "-- select --"}</option>}
                              {subjectNames.map((name) => (
                                <option key={name} value={name}>
                                  {name}
                                </option>
                              ))}
                            </select>
                            <input
                              type="time"
                              value={b.start_time}
                              onChange={(e) => updateBlock(currentGrade.grade, b.id, { start_time: e.target.value })}
                              aria-label={`${b.subject} start`}
                            />
                            <input
                              type="time"
                              value={b.end_time}
                              onChange={(e) => updateBlock(currentGrade.grade, b.id, { end_time: e.target.value })}
                              aria-label={`${b.subject} end`}
                            />
                            <span className="gsm-day-chips">
                              {WEEKDAYS.map((day) => (
                                <button
                                  type="button"
                                  key={day}
                                  className={`gsm-day-chip${b.days.includes(day) ? " on" : ""}`}
                                  aria-pressed={b.days.includes(day)}
                                  aria-label={day}
                                  onClick={() => toggleBlockDay(currentGrade.grade, b.id, day)}
                                >
                                  {DAY_SHORT[day]}
                                </button>
                              ))}
                            </span>
                            <button className="gsm-remove-btn" onClick={() => removeBlock(currentGrade.grade, b.id)}>
                              Remove
                            </button>
                          </div>
                        ))}
                      </div>

                      <div className="gsm-inline-actions">
                        <button className="gsm-add-btn" onClick={() => addBlock(currentGrade.grade)}>
                          + Add block
                        </button>
                        <button className="gsm-add-btn" onClick={() => sortBlocks(currentGrade.grade)}>
                          Sort by time
                        </button>
                        <label>
                          Copy these blocks to
                          <select
                            value=""
                            onChange={(e) => copyBlocks(currentGrade.grade, e.target.value)}
                          >
                            <option value="">-- grade --</option>
                            {grades
                              .filter((g) => g.grade !== currentGrade.grade)
                              .map((g) => (
                                <option key={g.grade} value={g.grade}>
                                  Grade {g.grade}
                                </option>
                              ))}
                          </select>
                        </label>
                        <button className="gsm-remove-btn" onClick={() => removeGrade(currentGrade.grade)}>
                          Remove grade {currentGrade.grade}
                        </button>
                      </div>
                    </>
                  )}
                </div>

                <MasterScheduleTimeline grades={grades} selectedGrade={selectedGrade} onSelect={setSelectedGrade} />
              </div>
            </div>
          )}

          {loadState === "ready" && tab === "rules" && (
            <div className="gsm-section">
              <p className="gsm-hint">
                Decide where services may happen. Pull-outs only land in blocks that allow them, and
                among those the scheduler prefers higher scores (I-Block 1000 is ideal; −400 means
                avoid unless there's no other time). Push-ins also need the service's own subject,
                e.g. SETSS for ELA pushes into ELA.
              </p>

              <div className="gsm-policy-list">
                <div className="gsm-policy-row gsm-policy-row-header">
                  <span>Block subject</span>
                  <span>Who teaches it</span>
                  <span>Pull-outs</span>
                  <span>Push-ins</span>
                  <span>Pull-out preference</span>
                  <span></span>
                </div>
                {policies.map((p) => (
                  <div className="gsm-policy-row" key={p.subject}>
                    <span className="gsm-policy-subject">
                      <span className="gsm-swatch" style={{ background: subjectColor(p.subject) }} />
                      {p.subject}
                    </span>
                    <select
                      value={p.role}
                      onChange={(e) => updatePolicy(p.subject, { role: e.target.value as BlockRole })}
                      aria-label={`${p.subject} role`}
                    >
                      {(Object.keys(ROLE_LABELS) as BlockRole[]).map((role) => (
                        <option key={role} value={role}>
                          {ROLE_LABELS[role]}
                        </option>
                      ))}
                    </select>
                    <input
                      type="checkbox"
                      checked={p.allow_pullout}
                      onChange={(e) => updatePolicy(p.subject, { allow_pullout: e.target.checked })}
                      aria-label={`Allow pull-outs during ${p.subject}`}
                    />
                    <input
                      type="checkbox"
                      checked={p.allow_pushin}
                      onChange={(e) => updatePolicy(p.subject, { allow_pushin: e.target.checked })}
                      aria-label={`Allow push-ins during ${p.subject}`}
                    />
                    <input
                      type="number"
                      step={50}
                      value={p.pullout_score}
                      disabled={!p.allow_pullout}
                      onChange={(e) => updatePolicy(p.subject, { pullout_score: Math.round(Number(e.target.value)) })}
                      aria-label={`${p.subject} pull-out preference`}
                    />
                    <button className="gsm-remove-btn" onClick={() => removePolicy(p.subject)}>
                      Remove
                    </button>
                  </div>
                ))}
              </div>
              <div className="gsm-inline-actions">
                <input
                  type="text"
                  placeholder="New block subject, e.g. Writing"
                  value={newSubjectName}
                  onChange={(e) => setNewSubjectName(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && addPolicy()}
                  aria-label="New block subject"
                />
                <button className="gsm-add-btn" onClick={addPolicy}>
                  + Add subject
                </button>
              </div>

              <label className="gsm-field">
                Max pullouts per student per day
                <input
                  type="number"
                  min={1}
                  value={pulloutConstraints.max_pullouts_per_day}
                  onChange={(e) =>
                    setPulloutConstraints((prev) => ({ ...prev, max_pullouts_per_day: Number(e.target.value) }))
                  }
                />
              </label>

              <label className="gsm-field">
                Minimum gap between pullouts (minutes)
                <input
                  type="number"
                  min={0}
                  value={pulloutConstraints.min_gap_minutes}
                  onChange={(e) =>
                    setPulloutConstraints((prev) => ({ ...prev, min_gap_minutes: Number(e.target.value) }))
                  }
                />
              </label>
            </div>
          )}

          {loadState === "ready" && tab === "specials" && (
            <div className="gsm-section">
              <p className="gsm-hint">
                Specials happen during each grade's Specials block, and each session lasts one block.
                Mandated subjects are booked first; the remaining blocks go to the other subjects
                below, in order.
              </p>
              <div className="gsm-specials-list">
                <div className="gsm-specials-row gsm-specials-row-header">
                  <span>Subject</span>
                  <span>Sessions / week</span>
                  <span></span>
                </div>
                {specials.map((s) => {
                  const mandate = MANDATED_SPECIALS[s.subject];
                  return (
                    <div className="gsm-specials-row" key={s.id}>
                      <input
                        type="text"
                        placeholder="e.g. Music"
                        value={s.subject}
                        onChange={(e) => updateSpecial(s.id, "subject", e.target.value)}
                        aria-label="Specials subject"
                      />
                      {mandate ? (
                        <span className="gsm-hint">
                          {shortestSpecialsBlock
                            ? `${Math.ceil(mandate / shortestSpecialsBlock)} per week (${mandate}-minute mandate ÷ ${shortestSpecialsBlock}-minute blocks)`
                            : `Set by the ${mandate}-minute weekly mandate`}
                        </span>
                      ) : (
                        <input
                          type="number"
                          min={1}
                          value={s.sessions_per_week}
                          onChange={(e) => updateSpecial(s.id, "sessions_per_week", Number(e.target.value))}
                          aria-label={`${s.subject} sessions per week`}
                        />
                      )}
                      <button className="gsm-remove-btn" onClick={() => removeSpecial(s.id)}>
                        Remove
                      </button>
                    </div>
                  );
                })}
              </div>
              <button className="gsm-add-btn" onClick={addSpecial}>
                + Add specials subject
              </button>

              <label className="gsm-checkbox-field">
                <input
                  type="checkbox"
                  checked={pulloutConstraints.allow_specials_merge}
                  onChange={(e) =>
                    setPulloutConstraints((prev) => ({ ...prev, allow_specials_merge: e.target.checked }))
                  }
                />
                Combine two homerooms into one specials class when no teacher is free
              </label>
            </div>
          )}
        </div>

        {isSubmitting && jobStatus && (
          <div className="gsm-progress">
            <div className="gsm-progress-track">
              <div className="gsm-progress-fill" style={{ width: `${displayedPercent}%` }} />
            </div>
            <div className="gsm-progress-label">
              {jobStatus.message || jobStatus.stage_name || "Starting…"} ({jobStatus.percent}%)
            </div>
          </div>
        )}

        {error && <div className="gsm-error">{error}</div>}

        <div className="gsm-footer">
          <button className="gsm-cancel-btn" onClick={onClose} disabled={isSubmitting}>
            Cancel
          </button>
          <button
            className="gsm-generate-btn"
            onClick={handleSubmit}
            disabled={isSubmitting || loadState !== "ready"}
          >
            {isSubmitting ? "Generating…" : "Generate Schedule"}
          </button>
        </div>
      </div>
    </div>
  );
}