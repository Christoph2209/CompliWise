import type { StaffScheduleEntry } from "../api/schedule";
import { CYCLE_DAYS as DAYS, dayLabel } from "../cycleDays";
import "./StudentSchedules.css";

const SPECIALS_SUBJECTS = ["PE", "Music", "Art"];

// Same vertical scale as the student calendar, so a block is the same
// height on both pages.
const PX_PER_MIN = 1.5;
const TICK_MINUTES = 30;

type RowKind = "pullout" | "push_in" | "flex" | "specials" | "prep" | "break" | "class";

const KIND_STYLES: Record<RowKind, { background: string; accent: string; label: string }> = {
  pullout: { background: "var(--green-100)", accent: "#15803d", label: "Pull-out service" },
  push_in: { background: "#e0f2f1", accent: "#0f766e", label: "Push-in service" },
  flex: { background: "var(--blue-100)", accent: "#1d4ed8", label: "FLEX / I-Block" },
  specials: { background: "#ece7f7", accent: "#6d28d9", label: "Specials" },
  prep: { background: "#f1f5f9", accent: "#94a3b8", label: "Prep" },
  break: { background: "var(--amber-100)", accent: "#b45309", label: "Lunch / recess" },
  class: { background: "var(--bg-page)", accent: "#64748b", label: "Class" },
};

function rowKind(row: StaffScheduleEntry): RowKind {
  if (row.delivery === "pullout") return "pullout";
  if (row.delivery === "push_in") return "push_in";
  if (row.delivery === "prep") return "prep";
  if (row.delivery === "break") return "break";
  if (row.is_flex_period) return "flex";
  const base = row.subject?.split(" - ")[0]?.trim() ?? "";
  if (row.block_subject === "Specials" || SPECIALS_SUBJECTS.includes(base)) return "specials";
  return "class";
}

function clockLabel(minute: number, withSuffix: boolean): string {
  const h = Math.floor(minute / 60);
  const m = minute % 60;
  const base = `${h % 12 || 12}:${String(m).padStart(2, "0")}`;
  return withSuffix ? `${base} ${h >= 12 ? "PM" : "AM"}` : base;
}

function hasStudents(row: StaffScheduleEntry): boolean {
  return row.delivery !== "prep" && row.delivery !== "break";
}

function studentsLabel(row: StaffScheduleEntry): string {
  return `${row.student_count} student${row.student_count === 1 ? "" : "s"}`;
}

interface StaffCalendarProps {
  /** One staff member's rows for one run. */
  rows: StaffScheduleEntry[];
  selectedId?: string | null;
  /** When given, rows that have students become clickable. */
  onSelect?: (row: StaffScheduleEntry) => void;
}

export default function StaffCalendar({ rows, selectedId, onSelect }: StaffCalendarProps) {
  if (rows.length === 0) return null;

  // The visible range is this person's day only, padded out to whole
  // half-hours so gridlines land on :00 and :30.
  const dayStart = Math.floor(Math.min(...rows.map((r) => r.start_minute)) / TICK_MINUTES) * TICK_MINUTES;
  const dayEnd = Math.ceil(Math.max(...rows.map((r) => r.end_minute)) / TICK_MINUTES) * TICK_MINUTES;
  const trackHeight = (dayEnd - dayStart) * PX_PER_MIN;
  const ticks: number[] = [];
  for (let m = dayStart; m <= dayEnd; m += TICK_MINUTES) ticks.push(m);

  function renderCardContent(row: StaffScheduleEntry, height: number) {
    const kind = rowKind(row);
    const badge = kind === "pullout" ? "Pull-out" : kind === "push_in" ? "Push-in" : null;
    const time = row.time_range ?? `${clockLabel(row.start_minute, false)}-${clockLabel(row.end_minute, false)}`;
    const detail = [row.room, hasStudents(row) ? studentsLabel(row) : null].filter(Boolean).join(" · ");

    if (height >= 46) {
      return (
        <>
          <strong className="cal-card-title">{row.subject}</strong>
          <span className="cal-card-line">{time}</span>
          {detail && <span className="cal-card-line">{detail}</span>}
          {badge && <span className="cal-card-badge">{badge}</span>}
        </>
      );
    }
    if (height >= 22) {
      return (
        <span className="cal-card-line">
          <strong>{row.subject}</strong> {time}
        </span>
      );
    }
    if (height >= 12) {
      return <span className="cal-card-tiny">{row.subject}</span>;
    }
    return null; // a 5-minute sliver: color strip only; details in the tooltip
  }

  return (
    <>
      <ul className="cal-legend" aria-label="Legend" style={{ marginBottom: "1rem" }}>
        {(Object.keys(KIND_STYLES) as RowKind[]).map((kind) => (
          <li key={kind}>
            <span
              className="cal-legend-swatch"
              style={{ background: KIND_STYLES[kind].background, borderColor: KIND_STYLES[kind].accent }}
            />
            {KIND_STYLES[kind].label}
          </li>
        ))}
      </ul>

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
              {rows
                .filter((r) => r.day_of_week === day)
                .map((row) => {
                  const kind = rowKind(row);
                  const style = KIND_STYLES[kind];
                  const top = (row.start_minute - dayStart) * PX_PER_MIN;
                  const height = Math.max((row.end_minute - row.start_minute) * PX_PER_MIN - 2, 3);
                  const tooltip = [
                    row.subject,
                    row.time_range,
                    row.room,
                    row.block_subject && row.block_subject !== row.subject ? `during ${row.block_subject}` : null,
                    hasStudents(row) ? studentsLabel(row) : null,
                  ]
                    .filter(Boolean)
                    .join("\n");
                  const cardStyle = {
                    top,
                    height,
                    background: style.background,
                    borderLeftColor: style.accent,
                  };

                  return onSelect && hasStudents(row) ? (
                    <button
                      type="button"
                      key={row.id}
                      className={`cal-card${selectedId === row.id ? " selected" : ""}`}
                      style={cardStyle}
                      title={tooltip}
                      onClick={() => onSelect(row)}
                    >
                      {renderCardContent(row, height)}
                    </button>
                  ) : (
                    <div key={row.id} className="cal-card" style={cardStyle} title={tooltip}>
                      {renderCardContent(row, height)}
                    </div>
                  );
                })}
            </div>
          ))}
        </div>
      </div>
    </>
  );
}
