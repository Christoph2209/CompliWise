import{ useMemo } from "react";
import { dayLabel } from "../cycleDays";

// A staff schedule row (one class/session for one teacher).
type StaffSlot = {
  staff_id?: string | null;
  day_of_week: string;
  start_minute: number;
  end_minute: number;
  time_range?: string | null;
  subject?: string;
  service_type?: string | null;
  room?: string | null;
};

// A per-student schedule entry from /schedule.
type ScheduleEntry = {
  staff_id?: string | null;
  day_of_week: string;
  start_minute?: number | null;
  end_minute?: number | null;
  subject?: string;
  room?: string | null;
  student_name?: string;
  student_id?: string;
};

type Props = {
  selectedSlot: StaffSlot | null;
  /** The run's student entries; null while they're still loading. */
  scheduleEntries: ScheduleEntry[] | null;
  onClose: () => void;
};

export default function StudentModal({
  selectedSlot,
  scheduleEntries,
  onClose,
}: Props) {
 // A class is every student entry with this teacher, day, subject and
 // room whose time overlaps the slot. A student pulled out mid-block
 // has two pieces of the same class, so dedupe by student.
 const students = useMemo(() => {
  if (!selectedSlot || !scheduleEntries) return [];

  const seen = new Map<string, string>();
  for (const entry of scheduleEntries) {
    if (
      entry.staff_id === selectedSlot.staff_id &&
      entry.day_of_week === selectedSlot.day_of_week &&
      entry.subject === selectedSlot.subject &&
      (entry.room ?? "") === (selectedSlot.room ?? "") &&
      typeof entry.start_minute === "number" &&
      typeof entry.end_minute === "number" &&
      entry.start_minute < selectedSlot.end_minute &&
      selectedSlot.start_minute < entry.end_minute
    ) {
      const key = entry.student_id ?? entry.student_name ?? "";
      if (!seen.has(key)) seen.set(key, entry.student_name || entry.student_id || "");
    }
  }
  return Array.from(seen.values()).sort((a, b) => a.localeCompare(b));
}, [scheduleEntries, selectedSlot]);

if (!selectedSlot) {
  return null; // early return now happens AFTER all hooks have run
}

  return (
    <div
      onClick={onClose}
      style={{
        position: "fixed",
        inset: 0,
        background: "rgba(15, 30, 22, 0.5)",
        display: "flex",
        justifyContent: "center",
        alignItems: "center",
        zIndex: 9999,
      }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{
          width: "420px",
          maxHeight: "75vh",
          overflowY: "auto",
          background: "#fff",
          borderRadius: "16px",
          padding: "20px",
          boxShadow: "0 20px 50px rgba(15, 30, 22, 0.25)",
        }}
      >
        {/* Header */}
        <div style={{ marginBottom: "10px" }}>
          <button
            onClick={onClose}
            style={{
              float: "right",
              border: "none",
              background: "var(--bg-page)",
              padding: "6px 10px",
              borderRadius: "8px",
              cursor: "pointer",
              color: "var(--text-h)",
            }}
          >
            ✕
          </button>

          <h2 style={{ margin: 0 }}>{selectedSlot.subject || "Class"}</h2>

          <p style={{ margin: "5px 0", color: "var(--text)" }}>
            {dayLabel(selectedSlot.day_of_week)}
            {selectedSlot.time_range ? ` • ${selectedSlot.time_range}` : ""}
            {selectedSlot.room ? ` • ${selectedSlot.room}` : ""}
          </p>

          {selectedSlot.service_type && (
            <span style={{ fontSize: "12px", color: "var(--text)" }}>
              {selectedSlot.service_type}
            </span>
          )}
        </div>

        <hr style={{ borderColor: "var(--border)" }} />

        {/* Students */}
        <h3 style={{ marginTop: "10px", color: "var(--text-h)" }}>
          Students{scheduleEntries ? ` (${students.length})` : ""}
        </h3>

        {scheduleEntries === null ? (
          <p style={{ color: "var(--text)" }}>Loading students…</p>
        ) : students.length === 0 ? (
          <p style={{ color: "var(--text)" }}>No students in this class</p>
        ) : (
          <ul style={{ paddingLeft: "18px", color: "var(--text-h)" }}>
            {students.map((name, index) => (
              <li key={index} style={{ marginBottom: "6px" }}>
                {name}
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
