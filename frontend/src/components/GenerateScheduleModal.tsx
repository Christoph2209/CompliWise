import { useState } from "react";
import { generateSchedule } from "../api/schedule";
import "./GenerateScheduleModal.css";

// ---------- Types ----------

export interface PeriodDefinition {
  id: string;
  name: string;
  start_time: string; // "HH:MM" 24hr
  end_time: string;   // "HH:MM" 24hr
  is_lunch?: boolean;
}

export interface PulloutConstraints {
  max_pullouts_per_day: number;
  min_gap_minutes: number;
  blackout_period_ids: string[]; // periods where pullouts are never allowed (lunch, recess, etc.)
  allow_specials_merge: boolean; // combine two homerooms into one shared specials session
}

export interface SpecialsRequirement {
  id: string;
  subject: string; // e.g. "PE", "Music", "Art", "Library"
  sessions_per_week: number;
  session_length_minutes: number;
}

export interface ScheduleGenerationConfig {
  periods: PeriodDefinition[];
  pullout_constraints: PulloutConstraints;
  specials_requirements: SpecialsRequirement[];
}

interface GenerateScheduleModalProps {
  onClose: () => void;
  onGenerated: () => void | Promise<void>;
}

// ---------- Defaults ----------
// Reasonable K-5 bell schedule starting point; fully editable by the user.

const DEFAULT_PERIODS: PeriodDefinition[] = [
  { id: "p1", name: "Period 1", start_time: "08:30", end_time: "09:15" },
  { id: "p2", name: "Period 2", start_time: "09:15", end_time: "10:00" },
  { id: "p3", name: "Period 3", start_time: "10:00", end_time: "10:45" },
  { id: "p4", name: "Period 4", start_time: "10:45", end_time: "11:30" },
  { id: "lunch", name: "Lunch", start_time: "11:30", end_time: "12:15", is_lunch: true },
  { id: "p5", name: "Period 5", start_time: "12:15", end_time: "13:00" },
  { id: "p6", name: "Period 6", start_time: "13:00", end_time: "13:45" },
  { id: "p7", name: "Period 7", start_time: "13:45", end_time: "14:30" },
];

const DEFAULT_SPECIALS: SpecialsRequirement[] = [
  { id: "sp1", subject: "PE", sessions_per_week: 3, session_length_minutes: 45 },
  { id: "sp2", subject: "Music", sessions_per_week: 2, session_length_minutes: 45 },
  { id: "sp3", subject: "Art", sessions_per_week: 1, session_length_minutes: 45 },
];

let idCounter = 0;
function nextId(prefix: string) {
  idCounter += 1;
  return `${prefix}_${Date.now()}_${idCounter}`;
}

type Tab = "periods" | "pullouts" | "specials";

export default function GenerateScheduleModal({ onClose, onGenerated }: GenerateScheduleModalProps) {
  const [tab, setTab] = useState<Tab>("periods");
  const [periods, setPeriods] = useState<PeriodDefinition[]>(DEFAULT_PERIODS);
  const [pulloutConstraints, setPulloutConstraints] = useState<PulloutConstraints>({
    max_pullouts_per_day: 2,
    min_gap_minutes: 30,
    blackout_period_ids: ["lunch"],
    allow_specials_merge: false,
  });
  const [specials, setSpecials] = useState<SpecialsRequirement[]>(DEFAULT_SPECIALS);

  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // ---------- Period handlers ----------

  function updatePeriod(id: string, field: keyof PeriodDefinition, value: string | boolean) {
    setPeriods((prev) =>
      prev.map((p) => (p.id === id ? { ...p, [field]: value } : p))
    );
  }

  function addPeriod() {
    const id = nextId("period");
    setPeriods((prev) => [
      ...prev,
      { id, name: `Period ${prev.length + 1}`, start_time: "09:00", end_time: "09:45" },
    ]);
  }

  function removePeriod(id: string) {
    setPeriods((prev) => prev.filter((p) => p.id !== id));
    setPulloutConstraints((prev) => ({
      ...prev,
      blackout_period_ids: prev.blackout_period_ids.filter((pid) => pid !== id),
    }));
  }

  // ---------- Pullout constraint handlers ----------

  function toggleBlackoutPeriod(id: string) {
    setPulloutConstraints((prev) => {
      const has = prev.blackout_period_ids.includes(id);
      return {
        ...prev,
        blackout_period_ids: has
          ? prev.blackout_period_ids.filter((pid) => pid !== id)
          : [...prev.blackout_period_ids, id],
      };
    });
  }

  // ---------- Specials handlers ----------

  function updateSpecial(id: string, field: keyof SpecialsRequirement, value: string | number) {
    setSpecials((prev) =>
      prev.map((s) => (s.id === id ? { ...s, [field]: value } : s))
    );
  }

  function addSpecial() {
    setSpecials((prev) => [
      ...prev,
      { id: nextId("special"), subject: "", sessions_per_week: 1, session_length_minutes: 45 },
    ]);
  }

  function removeSpecial(id: string) {
    setSpecials((prev) => prev.filter((s) => s.id !== id));
  }

  // ---------- Validation ----------

  function validate(): string | null {
    if (periods.length === 0) return "Add at least one period.";
    for (const p of periods) {
      if (!p.name.trim()) return "Every period needs a name.";
      if (!p.start_time || !p.end_time) return `${p.name || "A period"} is missing a start or end time.`;
      if (p.start_time >= p.end_time) return `${p.name}: start time must be before end time.`;
    }
    if (pulloutConstraints.max_pullouts_per_day < 1) return "Max pullouts per day must be at least 1.";
    if (pulloutConstraints.min_gap_minutes < 0) return "Minimum gap can't be negative.";
    for (const s of specials) {
      if (!s.subject.trim()) return "Every specials row needs a subject name.";
      if (s.sessions_per_week < 1) return `${s.subject || "A special"}: sessions per week must be at least 1.`;
      if (s.session_length_minutes < 1) return `${s.subject || "A special"}: session length must be positive.`;
    }
    return null;
  }

  async function handleSubmit() {
    const validationError = validate();
    if (validationError) {
      setError(validationError);
      return;
    }
    setError(null);
    setIsSubmitting(true);

    const config: ScheduleGenerationConfig = {
      periods,
      pullout_constraints: pulloutConstraints,
      specials_requirements: specials,
    };

    try {
      // NOTE: this assumes generateSchedule(config) is updated to accept
      // this payload and forward it to the backend's schedule-generation
      // endpoint. If generateSchedule() currently takes no arguments,
      // its signature and the corresponding FastAPI route/Pydantic model
      // will need to accept ScheduleGenerationConfig.
      await generateSchedule(config);
      await onGenerated();
      onClose();
    } catch (err) {
      console.error("Error generating schedule:", err);
      setError("Something went wrong generating the schedule. Check the console for details.");
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <div className="gsm-overlay" onClick={onClose}>
      <div className="gsm-modal" onClick={(e) => e.stopPropagation()}>
        <div className="gsm-header">
          <h2 style ={{ color: "#000000" }}>Generate Schedule</h2>
          <button className="gsm-close" onClick={onClose} aria-label="Close">
            ✕
          </button>
        </div>

        <div className="gsm-tabs">
          <button
            className={tab === "periods" ? "active" : ""}
            onClick={() => setTab("periods")}
          >
            Bell Schedule
          </button>
          <button
            className={tab === "pullouts" ? "active" : ""}
            onClick={() => setTab("pullouts")}
          >
            Pullout Constraints
          </button>
          <button
            className={tab === "specials" ? "active" : ""}
            onClick={() => setTab("specials")}
          >
            Specials
          </button>
        </div>

        <div className="gsm-body">
          {tab === "periods" && (
            <div className="gsm-section">
              <p className="gsm-hint">
                Define the periods of the school day. These times drive every slot the
                scheduler can place a FLEX group, mandated service, or special into.
              </p>
              <div className="gsm-period-list">
                <div className="gsm-period-row gsm-period-row-header">
                  <span>Name</span>
                  <span>Start</span>
                  <span>End</span>
                  <span>Lunch?</span>
                  <span></span>
                </div>
                {periods.map((p) => (
                  <div className="gsm-period-row" key={p.id}>
                    <input
                      type="text"
                      value={p.name}
                      onChange={(e) => updatePeriod(p.id, "name", e.target.value)}
                    />
                    <input
                      type="time"
                      value={p.start_time}
                      onChange={(e) => updatePeriod(p.id, "start_time", e.target.value)}
                    />
                    <input
                      type="time"
                      value={p.end_time}
                      onChange={(e) => updatePeriod(p.id, "end_time", e.target.value)}
                    />
                    <input
                      type="checkbox"
                      checked={!!p.is_lunch}
                      onChange={(e) => updatePeriod(p.id, "is_lunch", e.target.checked)}
                    />
                    <button className="gsm-remove-btn" onClick={() => removePeriod(p.id)}>
                      Remove
                    </button>
                  </div>
                ))}
              </div>
              <button className="gsm-add-btn" onClick={addPeriod}>
                + Add Period
              </button>
            </div>
          )}

          {tab === "pullouts" && (
            <div className="gsm-section">
              <p className="gsm-hint">
                Control how mandated pullout services (SETSS, ENL, IEP) and FLEX groups can
                be placed relative to each other and the rest of the day.
              </p>

              <label className="gsm-field">
                Max pullouts per student per day
                <input
                  type="number"
                  min={1}
                  value={pulloutConstraints.max_pullouts_per_day}
                  onChange={(e) =>
                    setPulloutConstraints((prev) => ({
                      ...prev,
                      max_pullouts_per_day: Number(e.target.value),
                    }))
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
                    setPulloutConstraints((prev) => ({
                      ...prev,
                      min_gap_minutes: Number(e.target.value),
                    }))
                  }
                />
              </label>

              <label className="gsm-checkbox-field">
                <input
                  type="checkbox"
                  checked={pulloutConstraints.allow_specials_merge}
                  onChange={(e) =>
                    setPulloutConstraints((prev) => ({
                      ...prev,
                      allow_specials_merge: e.target.checked,
                    }))
                  }
                />
                Allow merging two homerooms into one shared specials session
              </label>

              <div className="gsm-field">
                <div>Blackout periods (pullouts never scheduled here)</div>
                <div className="gsm-blackout-grid">
                  {periods.map((p) => (
                    <label key={p.id} className="gsm-blackout-chip">
                      <input
                        type="checkbox"
                        checked={pulloutConstraints.blackout_period_ids.includes(p.id)}
                        onChange={() => toggleBlackoutPeriod(p.id)}
                      />
                      {p.name}
                    </label>
                  ))}
                </div>
              </div>
            </div>
          )}

          {tab === "specials" && (
            <div className="gsm-section">
              <p className="gsm-hint">
                Set how many sessions per week each specials subject needs, and how long each
                session runs. The scheduler will place these algorithmically across open slots
                rather than a fixed period.
              </p>
              <div className="gsm-specials-list">
                <div className="gsm-specials-row gsm-specials-row-header">
                  <span>Subject</span>
                  <span>Sessions / week</span>
                  <span>Length (min)</span>
                  <span></span>
                </div>
                {specials.map((s) => (
                  <div className="gsm-specials-row" key={s.id}>
                    <input
                      type="text"
                      placeholder="e.g. PE"
                      value={s.subject}
                      onChange={(e) => updateSpecial(s.id, "subject", e.target.value)}
                    />
                    <input
                      type="number"
                      min={1}
                      value={s.sessions_per_week}
                      onChange={(e) =>
                        updateSpecial(s.id, "sessions_per_week", Number(e.target.value))
                      }
                    />
                    <input
                      type="number"
                      min={1}
                      value={s.session_length_minutes}
                      onChange={(e) =>
                        updateSpecial(s.id, "session_length_minutes", Number(e.target.value))
                      }
                    />
                    <button className="gsm-remove-btn" onClick={() => removeSpecial(s.id)}>
                      Remove
                    </button>
                  </div>
                ))}
              </div>
              <button className="gsm-add-btn" onClick={addSpecial}>
                + Add Specials Subject
              </button>
            </div>
          )}
        </div>

        {error && <div className="gsm-error">{error}</div>}

        <div className="gsm-footer">
          <button className="gsm-cancel-btn" onClick={onClose} disabled={isSubmitting}>
            Cancel
          </button>
          <button className="gsm-generate-btn" onClick={handleSubmit} disabled={isSubmitting}>
            {isSubmitting ? "Generating…" : "Generate Schedule"}
          </button>
        </div>
      </div>
    </div>
  );
}