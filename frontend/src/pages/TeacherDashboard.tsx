import { useEffect, useState } from "react";
import { getSchedule, getStaffSchedule, type StaffScheduleEntry } from "../api/schedule";
import { useAuth } from "../context/authContext";
import StaffCalendar from "../components/StaffCalendar";
import { CYCLE_DAYS, dayLabel } from "../cycleDays";
import "../components/Dashboard.css";

const DAYS: readonly string[] = CYCLE_DAYS;

function formatMinute(minute: number): string {
  const h = Math.floor(minute / 60);
  const m = minute % 60;
  return `${h % 12 || 12}:${String(m).padStart(2, "0")} ${h >= 12 ? "PM" : "AM"}`;
}

/**
 * When this teacher has one student, as lines like
 * "A, C days: 9:00 AM–9:30 AM". Back-to-back entries (Math then ELA
 * with the same homeroom teacher) are joined into one stretch, and
 * days with identical times share a line.
 */
function seenTimes(studentEntries: any[]): string[] {
  const timesByDay = new Map<string, string>();
  for (const day of DAYS) {
    const intervals = studentEntries
      .filter(
        (e) =>
          e.day_of_week === day &&
          typeof e.start_minute === "number" &&
          typeof e.end_minute === "number"
      )
      .map((e) => [e.start_minute, e.end_minute] as [number, number])
      .sort((a, b) => a[0] - b[0]);
    if (intervals.length === 0) continue;

    const merged: [number, number][] = [];
    for (const [start, end] of intervals) {
      const last = merged[merged.length - 1];
      if (last && start <= last[1]) last[1] = Math.max(last[1], end);
      else merged.push([start, end]);
    }
    // A student who's with the teacher on and off all day (a homeroom
    // class, broken up by lunch, specials and pull-outs) is shown as
    // one first-to-last window; the breaks are on the calendar above
    // and in the Pull outs panel. One or two sessions are listed as-is.
    const spans: [number, number][] =
      merged.length > 2 ? [[merged[0][0], merged[merged.length - 1][1]]] : merged;
    timesByDay.set(
      day,
      spans.map(([s, e]) => `${formatMinute(s)}–${formatMinute(e)}`).join(", ")
    );
  }

  const daysByTimes = new Map<string, string[]>();
  for (const [day, times] of timesByDay) {
    daysByTimes.set(times, [...(daysByTimes.get(times) ?? []), day]);
  }
  return Array.from(daysByTimes, ([times, days]) => {
    const label =
      days.length === DAYS.length
        ? "Every day"
        : `${days.join(", ")} day${days.length === 1 ? "" : "s"}`;
    return `${label}: ${times}`;
  });
}

/** PK, K, then 1, 2, 3... Unrecognized grades sort last. */
function gradeRank(grade: unknown): number {
  const text = String(grade ?? "").trim().toUpperCase();
  if (text === "PK") return -2;
  if (text === "K") return -1;
  const n = Number(text);
  return text !== "" && Number.isFinite(n) ? n : Number.MAX_SAFE_INTEGER;
}

/** The first time in the cycle this teacher has the student: earliest
 * day, then earliest start. Students with no timed entries sort last. */
function firstSeen(studentEntries: any[]): number {
  let first = Number.MAX_SAFE_INTEGER;
  for (const e of studentEntries) {
    const dayIndex = DAYS.indexOf(e.day_of_week);
    if (dayIndex < 0 || typeof e.start_minute !== "number") continue;
    first = Math.min(first, dayIndex * 24 * 60 + e.start_minute);
  }
  return first;
}

export default function TeacherDashboard() {
  const { user } = useAuth();
  const [rows, setRows] = useState<StaffScheduleEntry[]>([]);
  const [entries, setEntries] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function load() {
      try {
        // The server only returns this teacher's rows, from the latest run.
        const myRows = (await getStaffSchedule()) || [];
        setRows(myRows);
        // Roster comes from the same run's student entries.
        const runId = myRows[0]?.run_id;
        if (runId) setEntries((await getSchedule(runId)) || []);
      } catch (err) {
        console.error("Error loading your schedule:", err);
      } finally {
        setLoading(false);
      }
    }
    load();
  }, []);

  // Only this teacher's schedule entries
  const myStaffId = user?.staff_member?.id;
  const myEntries = entries.filter((e) => e.staff_id === myStaffId);

  // Unique roster derived from those entries
  const roster = Array.from(
    new Map(
      myEntries.map((e) => [
        e.student_id,
        { id: e.student_id, name: e.student_name, grade: e.grade },
      ])
    ).values()
  )
    .map((s) => {
      const studentEntries = myEntries.filter((e) => e.student_id === s.id);
      return { ...s, seen: seenTimes(studentEntries), firstSeen: firstSeen(studentEntries) };
    })
    // Grade first, then when they're first seen in the cycle, then name.
    .sort(
      (a, b) =>
        gradeRank(a.grade) - gradeRank(b.grade) ||
        a.firstSeen - b.firstSeen ||
        a.name.localeCompare(b.name)
    );

  // Every pull-out for a roster student, whoever delivers it -- so a
  // homeroom teacher can see who's coming for which student and when.
  const rosterIds = new Set(roster.map((s) => s.id));
  const pullouts = entries
    .filter(
      (e) =>
        rosterIds.has(e.student_id) &&
        (e.delivery === "pullout" || (e.delivery == null && e.is_pullout))
    )
    .sort(
      (a, b) =>
        DAYS.indexOf(a.day_of_week) - DAYS.indexOf(b.day_of_week) ||
        (a.start_minute ?? 0) - (b.start_minute ?? 0) ||
        String(a.student_name).localeCompare(String(b.student_name))
    );
  const pulloutDays = DAYS.filter((day) => pullouts.some((p) => p.day_of_week === day));

  if (loading) {
    return (
      <div className="dashboard">
        <p>Loading your schedule...</p>
      </div>
    );
  }

  return (
    <div className="dashboard">
      <div className="dashboard-header">
        <h1>My Dashboard</h1>
      </div>

      <section style={{ marginBottom: 32 }}>
        <h2>My Weekly Schedule</h2>
        {rows.length === 0 ? (
          <p>You don't have a schedule yet.</p>
        ) : (
          <StaffCalendar rows={rows} />
        )}
      </section>

      <div style={{ display: "flex", flexWrap: "wrap", gap: 24, alignItems: "flex-start" }}>
      <section style={{ flex: "1 1 480px", minWidth: 0 }}>
        <h2>My Class Roster ({roster.length})</h2>
        {roster.length === 0 ? (
          <p>No students currently assigned to your schedule.</p>
        ) : (
          <table className="dashboard-table">
            <thead>
              <tr>
                <th>Name</th>
                <th>Grade</th>
                <th>When seen</th>
              </tr>
            </thead>
            <tbody>
              {roster.map((s) => (
                <tr key={s.id}>
                  <td>{s.name}</td>
                  <td>{s.grade}</td>
                  <td>
                    {s.seen.map((line) => (
                      <div key={line}>{line}</div>
                    ))}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      <aside className="panel" style={{ flex: "0 0 320px", height: "auto" }}>
        <h2>Pull outs ({pullouts.length})</h2>
        {pullouts.length === 0 ? (
          <p>None of your students are pulled out.</p>
        ) : (
          pulloutDays.map((day) => (
            <div key={day} style={{ marginBottom: 14 }}>
              <strong>{dayLabel(day)}</strong>
              <ul style={{ listStyle: "none", margin: "6px 0 0", padding: 0 }}>
                {pullouts
                  .filter((p) => p.day_of_week === day)
                  .map((p) => (
                    <li
                      key={p.id}
                      style={{ padding: "6px 0", borderTop: "1px solid var(--border)", fontSize: 14 }}
                    >
                      <div>
                        <strong>{p.student_name}</strong> · {p.time_range}
                      </div>
                      <div style={{ color: "var(--text)" }}>
                        {p.subject} with {p.staff_name || "no provider assigned"}
                      </div>
                    </li>
                  ))}
              </ul>
            </div>
          ))
        )}
      </aside>
      </div>
    </div>
  );
}
