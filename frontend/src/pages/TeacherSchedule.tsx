import { useEffect, useMemo, useState } from "react";
import { getSchedule, getStaffSchedule, type StaffScheduleEntry } from "../api/schedule";
import { cachedFetch } from "../api/apiCache";
import StaffCalendar from "../components/StaffCalendar";
import StudentModal from "../components/StudentModal";
import RunSelector from "../components/RunSelector";
import { useAuth } from "../context/authContext";

// Rows saved without a matching staff record have no staff_id; fall
// back to the name so they still get their own entry in the selector.
function staffKey(row: StaffScheduleEntry): string {
  return row.staff_id ?? `name:${row.staff_name ?? ""}`;
}

export default function TeacherSchedules() {
  const { user } = useAuth();
  const canCompareRuns = user?.role === "admin" || user?.role === "principal";

  const [rows, setRows] = useState<StaffScheduleEntry[]>([]);
  const [loadState, setLoadState] = useState<"loading" | "ready" | "error">("loading");
  const [selectedTeacher, setSelectedTeacher] = useState("");
  const [selectedSlot, setSelectedSlot] = useState<StaffScheduleEntry | null>(null);
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
  // Student entries for the run, used to list who's in a clicked class.
  const [studentEntries, setStudentEntries] = useState<any[] | null>(null);

  const runKey = canCompareRuns ? selectedRunId ?? "default" : "default";

  useEffect(() => {
    if (canCompareRuns && selectedRunId === null) return; // wait for RunSelector to set a default

    let cancelled = false;

    async function load() {
      setLoadState("loading");
      setSelectedSlot(null);
      setStudentEntries(null);
      try {
        const data =
          (await cachedFetch(`staff-schedule:${runKey}`, () =>
            getStaffSchedule(canCompareRuns ? selectedRunId! : undefined)
          )) || [];
        if (cancelled) return;
        setRows(data);
        setSelectedTeacher((prev) =>
          prev && data.some((r) => staffKey(r) === prev) ? prev : data.length > 0 ? staffKey(data[0]) : ""
        );
        setLoadState("ready");

        // Same cache key format as StudentSchedules, so the two pages
        // share one fetch of a run's student entries.
        const runId = data[0]?.run_id;
        if (runId) {
          const entries = (await cachedFetch(`schedule:${runId}`, () => getSchedule(runId))) || [];
          if (!cancelled) setStudentEntries(entries);
        }
      } catch (err) {
        console.error("Error loading staff schedules:", err);
        if (!cancelled) setLoadState("error");
      }
    }

    load();
    return () => {
      cancelled = true;
    };
  }, [canCompareRuns, selectedRunId, runKey]);

  const staff = useMemo(
    () =>
      Array.from(
        new Map(rows.map((r) => [staffKey(r), { id: staffKey(r), name: r.staff_name || "Unknown" }])).values()
      ).sort((a, b) => a.name.localeCompare(b.name)),
    [rows]
  );

  const teacherRows = useMemo(
    () => rows.filter((r) => staffKey(r) === selectedTeacher),
    [rows, selectedTeacher]
  );

  return (
    <div style={{ padding: "28px 36px" }}>
      <h1 style={{ marginBottom: "16px" }}>{canCompareRuns ? "Staff Schedules" : "My Schedule"}</h1>

      {canCompareRuns && (
        <RunSelector selectedRunId={selectedRunId} onChange={setSelectedRunId} />
      )}

      {loadState === "error" && (
        <p className="cal-notice">The staff schedule couldn't be loaded. Try refreshing.</p>
      )}

      {loadState === "ready" && rows.length === 0 && (
        <p className="cal-notice">
          {canCompareRuns
            ? "This run has no saved staff schedules. Runs made before staff schedules were saved don't have them, so generate a new schedule to see them here."
            : "You don't have a schedule yet."}
        </p>
      )}

      {/* Staff Selector */}
      {staff.length > 1 && (
        <div className="cal-toolbar">
          <label>
            <span style={{ marginRight: "10px", fontWeight: "bold" }}>Staff:</span>
            <select
              value={selectedTeacher}
              onChange={(e) => {
                setSelectedTeacher(e.target.value);
                setSelectedSlot(null);
              }}
            >
              {staff.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.name}
                </option>
              ))}
            </select>
          </label>
        </div>
      )}

      <StaffCalendar rows={teacherRows} selectedId={selectedSlot?.id} onSelect={setSelectedSlot} />

      <StudentModal
        selectedSlot={selectedSlot}
        scheduleEntries={studentEntries}
        onClose={() => setSelectedSlot(null)}
      />
    </div>
  );
}
