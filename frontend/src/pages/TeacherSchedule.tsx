import { useEffect, useState } from "react";
import { getSchedule } from "../api/schedule";
import { cachedFetch } from "../api/apiCache";
import StudentModal from "../components/StudentModal";
import RunSelector from "../components/RunSelector";
import { useAuth } from "../context/authContext";

const DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"];
const PERIODS = [1, 2, 3, 4, 5, 6, 7];

export default function TeacherSchedules() {
  const { user } = useAuth();
  const canCompareRuns = user?.role === "admin" || user?.role === "principal";

  const [entries, setEntries] = useState<any[]>([]);
  const [selectedTeacher, setSelectedTeacher] = useState("");
  const [selectedSlot, setSelectedSlot] = useState<any>(null);
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);

  // Same cache key format as StudentSchedules — the two pages fetch the
  // same underlying schedule for a run, so this reuses that entry instead
  // of firing a second identical request when the user switches pages.
  const runKey = canCompareRuns ? selectedRunId ?? "default" : "default";

  useEffect(() => {
    if (canCompareRuns && selectedRunId === null) return;

    async function load() {
      const data =
        (await cachedFetch(`schedule:${runKey}`, () =>
          getSchedule(canCompareRuns ? selectedRunId! : undefined)
        )) || [];
      setEntries(data);

      if (data.length > 0) {
        setSelectedTeacher((prev) => prev || data[0].staff_id);
      }
    }

    load();
  }, [canCompareRuns, selectedRunId, runKey]);
  // Build staff list
 const staff = Array.from(
  new Map(
    entries
      .filter((e) => e.staff_id)
      .map((entry) => [
        entry.staff_id,
        {
          id: entry.staff_id,
          name: entry.staff_name,
        },
      ])
  ).values()
);

const periodLabels: Record<number, string> = {};
  entries.forEach((e) => {
    if (e.period_label) periodLabels[Number(e.period)] = e.period_label;
});

  const teacherSchedule = entries.filter(
    (entry) => entry.staff_id === selectedTeacher
  );

  function getClass(day: string, period: number) {
    return teacherSchedule.find(
      (entry) =>
        entry.day_of_week === day &&
        Number(entry.period) === period
    );
  }
function getStudentCount(day: string, period: number) {
  return teacherSchedule.filter(
    (entry) =>
      entry.day_of_week === day &&
      Number(entry.period) === period
  ).length;
}
  return (
    <div style={{ padding: "28px 36px" }}>
      <h1 style={{ marginBottom: "16px" }}>Staff Schedules</h1>

      {canCompareRuns && (
        <RunSelector selectedRunId={selectedRunId} onChange={setSelectedRunId} />
      )}
      {/* Staff Selector */}
      <div style={{ marginBottom: "20px" }}>
        <label style={{ marginRight: "10px", fontWeight: "bold" }}>
          Staff:
        </label>

        <select
          value={selectedTeacher}
          onChange={(e) => setSelectedTeacher(e.target.value)}
          style={{
            padding: "8px 12px",
            borderRadius: "10px",
            border: "1.5px solid var(--border)",
            fontFamily: "var(--font-body)",
          }}
        >
          {staff.map((s) => (
            <option key={s.id} value={s.id}>
              {s.name}
            </option>
          ))}
        </select>
      </div>

      {/* Grid */}
      {selectedTeacher && (
        <table
          style={{
            width: "100%",
            borderCollapse: "separate",
            borderSpacing: "10px",
          }}
        >
          <thead>
            <tr>
              <th style={{ padding: "8px" }}>Period</th>
              {DAYS.map((day) => (
                <th key={day} style={{ padding: "8px", textTransform: "capitalize" }}>
                  {day}
                </th>
              ))}
            </tr>
          </thead>

          <tbody>
            {PERIODS.map((period) => (
              <tr key={period}>
                <td style={{ fontWeight: "bold", textAlign: "center" }}>
                  {periodLabels[period] ?? `Period ${period}`}
                </td>

                {DAYS.map((day) => {
                  const item = getClass(day, period);

                  return (
                   <td
                    key={day}
                    onClick={() => {
                      console.log("clicked", item);
                      if (item) setSelectedSlot(item);
                    }}
                    style={{
                      minWidth: "140px",
                      height: "90px",
                      verticalAlign: "top",
                      background: item ? "var(--green-100)" : "white",
                      borderRadius: "10px",
                      padding: "10px",
                      border: "1px solid var(--border)",
                      position: "relative",
                      cursor: item ? "pointer" : "default",
                    }}
                  >
                    {item ? (
                        <div style={{ fontSize: "13px" }}>
                        <strong style={{ display: "block", marginBottom: "4px", color: "var(--text-h)" }}>
                            {item.subject}
                        </strong>

                        <span style={{ display: "block", color: "var(--text)" }}>
                            {item.staff_name || "No Teacher"}
                        </span>

                        <small style={{ display: "block", marginTop: "4px", color: "var(--text)" }}>
                            {item.service_type}
                        </small>

                        {item.is_pullout && (
                            <div
                            style={{
                                marginTop: "6px",
                                fontSize: "11px",
                                color: "var(--red-500)",
                                fontWeight: "bold",
                            }}
                            >
                            PULL OUT
                            </div>
                        )}

                        {/* student count badge */}
                        <div
                            style={{
                            position: "absolute",
                            top: "6px",
                            right: "6px",
                            background: "var(--green-700)",
                            color: "white",
                            fontSize: "11px",
                            padding: "2px 6px",
                            borderRadius: "999px",
                            }}
                        >
                            {getStudentCount(day, period)}
                        </div>
                        </div>
                    ) : (
                        <span style={{ color: "var(--text)" }}>—</span>
                    )}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <StudentModal
        selectedSlot={selectedSlot}
        teacherSchedule={teacherSchedule}
        onClose={() => setSelectedSlot(null)}
      />
    </div>
  );
}