import { useEffect, useMemo, useState } from "react";
import { getSchedule, updateScheduleEntry } from "../api/schedule";
import { getStaff } from "../api/staff";
import { cachedFetch, invalidateCache } from "../api/apiCache";
import { useAuth } from "../context/authContext";
import RunSelector from "../components/RunSelector";
import { CYCLE_DAYS as DAYS, dayLabel } from "../cycleDays";
import "../components/StudentSchedules.css";


const SPECIALS_SUBJECTS = ["PE", "Music", "Art"];

// Vertical scale of the calendar. 1.5px/min makes a 45-minute block
// ~68px tall -- room for subject, time, and teacher.
const PX_PER_MIN = 1.5;
const TICK_MINUTES = 30;

type Delivery = "pullout" | "push_in" | "class";

interface StaffMember {
  id: string;
  first_name: string;
  last_name: string;
  title?: string;
}

interface ScheduleEntry {
  id: string;
  student_id: string;
  student_name: string;
  grade: string;
  day_of_week: string;
  period: number; // == start_minute for runs made with the master schedule
  period_label?: string;
  subject: string;
  staff_id?: string | null;
  staff_name?: string | null;
  service_type?: string;
  is_pullout: boolean;
  is_flex_period?: boolean;
  start_minute?: number | null;
  end_minute?: number | null;
  time_range?: string | null;
  delivery?: Delivery | null;
  block_subject?: string | null;
  room?: string | null;
}

interface EditDraft {
  subject: string;
  staff_id: string;
  service_type: string;
  delivery: Delivery;
}

type EntryKind = "pullout" | "push_in" | "flex" | "specials" | "lunch" | "class";

const KIND_STYLES: Record<EntryKind, { background: string; accent: string; label: string }> = {
  pullout: { background: "var(--green-100)", accent: "#15803d", label: "Pull-out service" },
  push_in: { background: "#e0f2f1", accent: "#0f766e", label: "Push-in service" },
  flex: { background: "var(--blue-100)", accent: "#1d4ed8", label: "FLEX / I-Block" },
  specials: { background: "#ece7f7", accent: "#6d28d9", label: "Specials" },
  lunch: { background: "var(--amber-100)", accent: "#b45309", label: "Lunch / recess" },
  class: { background: "var(--bg-page)", accent: "#64748b", label: "Class" },
};

function entryKind(item: ScheduleEntry): EntryKind {
  // Services first: a pull-out during I-Block is a service, not FLEX.
  if (item.delivery === "pullout" || (item.delivery == null && item.is_pullout)) return "pullout";
  if (item.delivery === "push_in") return "push_in";
  if (item.is_flex_period) return "flex";
  const block = item.block_subject ?? "";
  if (block === "Lunch" || block === "Recess" || item.subject === "Lunch/Recess") return "lunch";
  const base = item.subject?.split(" - ")[0]?.trim() ?? "";
  if (block === "Specials" || SPECIALS_SUBJECTS.includes(base)) return "specials";
  return "class";
}

function hasTimes(item: ScheduleEntry): item is ScheduleEntry & { start_minute: number; end_minute: number } {
  return typeof item.start_minute === "number" && typeof item.end_minute === "number";
}

function clockLabel(minute: number, withSuffix: boolean): string {
  const h = Math.floor(minute / 60);
  const m = minute % 60;
  const base = `${h % 12 || 12}:${String(m).padStart(2, "0")}`;
  return withSuffix ? `${base} ${h >= 12 ? "PM" : "AM"}` : base;
}

function errorMessage(err: unknown): string {
  const anyErr = err as { response?: { status?: number; data?: { detail?: unknown } }; message?: string };
  const detail = anyErr?.response?.data?.detail;
  if (typeof detail === "string") return detail;
  if (anyErr?.response?.status) return `The server rejected the change (${anyErr.response.status}).`;
  return anyErr?.message ?? "The change couldn't be saved.";
}

export default function StudentSchedules() {
  const { user } = useAuth();
  const isTeacher = user?.role === "teacher";
  const canCompareRuns = user?.role === "admin" || user?.role === "principal";
  const myStaffId = user?.staff_member?.id;

  const [entries, setEntries] = useState<ScheduleEntry[]>([]);
  const [selectedStudent, setSelectedStudent] = useState<string | null>(null);
  const [editingEntry, setEditingEntry] = useState<ScheduleEntry | null>(null);
  const [draft, setDraft] = useState<EditDraft | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [isSaving, setIsSaving] = useState(false);
  const [staff, setStaff] = useState<StaffMember[]>([]);
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);

  // Same run maps to the same cache entry no matter which page fetched it,
  // so switching between Student/Staff schedule views for one run reuses
  // the cached data instead of re-fetching.
  const runKey = canCompareRuns ? selectedRunId ?? "default" : "default";

  useEffect(() => {
    // Teachers always see the current/default run; only admins/principals compare runs
    if (canCompareRuns && selectedRunId === null) return; // wait for RunSelector to set a default

    async function load() {
      const [scheduleData, staffData] = await Promise.all([
        cachedFetch(`schedule:${runKey}`, () =>
          getSchedule(canCompareRuns ? selectedRunId! : undefined)
        ),
        // Staff lists change far less often than schedules, so keep them
        // fresh for longer to avoid re-fetching on every page visit.
        cachedFetch("staff:all", () => getStaff(), { staleMs: 5 * 60_000 }),
      ]);

      const allEntries: ScheduleEntry[] = scheduleData || [];

      let visibleEntries = allEntries;

      if (isTeacher && myStaffId) {
        // Students on this teacher's roster: any entry where they're the
        // assigned staff. Then show those students' FULL schedules.
        const myStudentIds = new Set(
          allEntries.filter((e) => e.staff_id === myStaffId).map((e) => e.student_id)
        );
        visibleEntries = allEntries.filter((e) => myStudentIds.has(e.student_id));
      }

      setEntries(visibleEntries);
      setStaff(staffData || []);
      setEditingEntry(null);
      setDraft(null);

      setSelectedStudent((prev) => {
        if (prev && visibleEntries.some((e) => e.student_id === prev)) {
          return prev;
        }
        return visibleEntries.length > 0 ? visibleEntries[0].student_id : null;
      });
    }

    load();
  }, [isTeacher, myStaffId, canCompareRuns, selectedRunId, runKey]);

  const students = useMemo(
    () =>
      Array.from(
        new Map(
          entries.map((e) => [e.student_id, { id: e.student_id, name: e.student_name, grade: e.grade }])
        ).values()
      ).sort((a, b) => a.name.localeCompare(b.name)),
    [entries]
  );

  const studentSchedule = useMemo(
    () => entries.filter((e) => e.student_id === selectedStudent),
    [entries, selectedStudent]
  );

  const timedEntries = studentSchedule.filter(hasTimes);
  const untimedCount = studentSchedule.length - timedEntries.length;

  // The visible range is this student's day only, padded out to whole
  // half-hours so gridlines land on :00 and :30.
  const dayStart = timedEntries.length
    ? Math.floor(Math.min(...timedEntries.map((e) => e.start_minute)) / TICK_MINUTES) * TICK_MINUTES
    : 0;
  const dayEnd = timedEntries.length
    ? Math.ceil(Math.max(...timedEntries.map((e) => e.end_minute)) / TICK_MINUTES) * TICK_MINUTES
    : 0;
  const trackHeight = (dayEnd - dayStart) * PX_PER_MIN;
  const ticks: number[] = [];
  for (let m = dayStart; m <= dayEnd; m += TICK_MINUTES) ticks.push(m);

  function openEditor(item: ScheduleEntry) {
    if (isTeacher) return;
    setSaveError(null);
    setEditingEntry(item);
    setDraft({
      subject: item.subject ?? "",
      staff_id: item.staff_id ?? "",
      service_type: item.service_type ?? "",
      delivery: item.delivery ?? (item.is_pullout ? "pullout" : "class"),
    });
  }

  function closeEditor() {
    setEditingEntry(null);
    setDraft(null);
    setSaveError(null);
  }

  async function saveEdit() {
    if (!editingEntry || !draft) return;
    setIsSaving(true);
    setSaveError(null);

    // Only the fields PUT /schedule/{id} accepts -- sending the whole
    // entry gets rejected.
    const payload = {
      subject: draft.subject,
      staff_id: draft.staff_id || null,
      service_type: draft.service_type,
      delivery: draft.delivery,
    };

    try {
      await updateScheduleEntry(editingEntry.id, payload);

      const assigned = staff.find((s) => s.id === draft.staff_id);
      const updated: ScheduleEntry = {
        ...editingEntry,
        subject: draft.subject,
        staff_id: assigned?.id ?? null,
        staff_name: assigned ? `${assigned.first_name} ${assigned.last_name}` : "",
        service_type: draft.service_type,
        delivery: draft.delivery,
        is_pullout: draft.delivery === "pullout",
      };
      setEntries((prev) => prev.map((e) => (e.id === updated.id ? updated : e)));

      // The cached schedule for this run is now stale server-side -- drop
      // it so the next load anywhere pulls fresh data.
      invalidateCache(`schedule:${runKey}`);
      closeEditor();
    } catch (err) {
      setSaveError(errorMessage(err));
    } finally {
      setIsSaving(false);
    }
  }

  function renderCardContent(item: ScheduleEntry & { start_minute: number; end_minute: number }, height: number) {
    const kind = entryKind(item);
    const badge = kind === "pullout" ? "Pull-out" : kind === "push_in" ? "Push-in" : null;
    const time = item.time_range ?? `${clockLabel(item.start_minute, false)}-${clockLabel(item.end_minute, false)}`;
    // Specials are stored as "PE - 2A", naming the class's HOST homeroom;
    // for a merged class that's another homeroom, so show just "PE".
    const title = kind === "specials" ? item.subject.split(" - ")[0].trim() : item.subject;

    if (height >= 46) {
      return (
        <>
          <strong className="cal-card-title">{title}</strong>
          <span className="cal-card-line">{time}</span>
          {item.staff_name && <span className="cal-card-line">{item.staff_name}</span>}
          {badge && <span className="cal-card-badge">{badge}</span>}
        </>
      );
    }
    if (height >= 22) {
      return (
        <span className="cal-card-line">
          <strong>{title}</strong> {time}
        </span>
      );
    }
    if (height >= 12) {
      return <span className="cal-card-tiny">{title}</span>;
    }
    return null; // a 5-minute sliver: color strip only; details in the tooltip
  }

  return (
    <div style={{ padding: "28px 36px" }}>
      <h1>{isTeacher ? "My Students' Schedules" : "Student Schedules"}</h1>

      {canCompareRuns && <RunSelector selectedRunId={selectedRunId} onChange={setSelectedRunId} />}

      {isTeacher && students.length === 0 && <p>No students are currently assigned to your schedule.</p>}

      <div className="cal-toolbar">
        <select
          value={selectedStudent || ""}
          onChange={(e) => {
            setSelectedStudent(e.target.value || null);
            closeEditor();
          }}
          aria-label="Student"
        >
          {students.length === 0 && <option value="">Loading students…</option>}
          {students.map((s) => (
            <option key={s.id} value={s.id}>
              {s.name}
              {s.grade ? ` (Grade ${s.grade})` : ""}
            </option>
          ))}
        </select>

        <ul className="cal-legend" aria-label="Legend">
          {(Object.keys(KIND_STYLES) as EntryKind[]).map((kind) => (
            <li key={kind}>
              <span
                className="cal-legend-swatch"
                style={{ background: KIND_STYLES[kind].background, borderColor: KIND_STYLES[kind].accent }}
              />
              {KIND_STYLES[kind].label}
            </li>
          ))}
        </ul>
      </div>

      {untimedCount > 0 && (
        <p className="cal-notice">
          {untimedCount} of this student's entries come from a schedule made before the master
          schedule existed and have no start/end times. Generate a new schedule to see them here.
        </p>
      )}

      {timedEntries.length > 0 && (
        <div className="cal-scroll">
          <div className="cal-grid">
            <div />
            {DAYS.map((day) => (
              <div key={day} className="cal-day-head">
                {dayLabel(day)}
              </div>
            ))}

            <div className="cal-axis" style={{ height: trackHeight }}>
              {ticks.map((m) => (
                <span key={m} className="cal-axis-label" style={{ top: (m - dayStart) * PX_PER_MIN }}>
                  {clockLabel(m, m % 60 === 0)}
                </span>
              ))}
            </div>

            {DAYS.map((day) => (
              <div
                key={day}
                className="cal-day"
                style={{
                  height: trackHeight,
                  backgroundSize: `100% ${TICK_MINUTES * PX_PER_MIN}px`,
                }}
              >
                {timedEntries
                  .filter((e) => e.day_of_week === day)
                  .map((item) => {
                    const kind = entryKind(item);
                    const style = KIND_STYLES[kind];
                    const top = (item.start_minute - dayStart) * PX_PER_MIN;
                    const height = Math.max((item.end_minute - item.start_minute) * PX_PER_MIN - 2, 3);
                    const tooltip = [
                      item.subject,
                      item.time_range,
                      item.staff_name,
                      item.block_subject && item.block_subject !== item.subject ? `during ${item.block_subject}` : null,
                      kind === "pullout" ? "Pull-out" : kind === "push_in" ? "Push-in" : null,
                    ]
                      .filter(Boolean)
                      .join("\n");
                    const isSelected = editingEntry?.id === item.id;
                    const cardStyle = {
                      top,
                      height,
                      background: style.background,
                      borderLeftColor: style.accent,
                    };

                    return isTeacher ? (
                      <div key={item.id} className="cal-card" style={cardStyle} title={tooltip}>
                        {renderCardContent(item, height)}
                      </div>
                    ) : (
                      <button
                        type="button"
                        key={item.id}
                        className={`cal-card${isSelected ? " selected" : ""}`}
                        style={cardStyle}
                        title={tooltip}
                        onClick={() => openEditor(item)}
                      >
                        {renderCardContent(item, height)}
                      </button>
                    );
                  })}
              </div>
            ))}
          </div>
        </div>
      )}

      {editingEntry && draft && !isTeacher && (
        <section className="cal-editor" aria-label="Edit schedule entry">
          <h2>
            {dayLabel(editingEntry.day_of_week)} {editingEntry.time_range}
            {editingEntry.block_subject ? `, during ${editingEntry.block_subject}` : ""}
          </h2>

          <label>
            Subject
            <input value={draft.subject} onChange={(e) => setDraft({ ...draft, subject: e.target.value })} />
          </label>

          <label>
            Teacher / provider
            <select value={draft.staff_id} onChange={(e) => setDraft({ ...draft, staff_id: e.target.value })}>
              <option value="">Unassigned</option>
              {staff.map((t) => (
                <option key={t.id} value={t.id}>
                  {t.first_name} {t.last_name}
                  {t.title ? ` (${t.title})` : ""}
                </option>
              ))}
            </select>
          </label>

          <label>
            Service type
            <input
              value={draft.service_type}
              onChange={(e) => setDraft({ ...draft, service_type: e.target.value })}
            />
          </label>

          <label>
            Delivery
            <select
              value={draft.delivery}
              onChange={(e) => setDraft({ ...draft, delivery: e.target.value as Delivery })}
            >
              <option value="class">Class</option>
              <option value="pullout">Pull-out</option>
              <option value="push_in">Push-in</option>
            </select>
          </label>

          {saveError && <p className="cal-error">{saveError}</p>}

          <div className="cal-editor-actions">
            <button onClick={saveEdit} disabled={isSaving}>
              {isSaving ? "Saving…" : "Save"}
            </button>
            <button onClick={closeEditor} disabled={isSaving}>
              Cancel
            </button>
          </div>
          <p className="cal-hint">
            Changes here don't move the entry in time. Run the compliance check afterwards to catch
            double-bookings or services in blocks that don't allow them.
          </p>
        </section>
      )}
    </div>
  );
}