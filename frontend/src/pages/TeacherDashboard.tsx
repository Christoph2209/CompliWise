import { useEffect, useState } from "react";
import { getSchedule } from "../api/schedule";
import { useAuth } from "../context/authContext";
import "../components/Dashboard.css";

const DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"];
const PERIODS = [1, 2, 3, 4, 5, 6, 7];

export default function TeacherDashboard() {
  const { user } = useAuth();
  const [entries, setEntries] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    getSchedule()
      .then((data) => setEntries(data || []))
      .finally(() => setLoading(false));
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
  );

  function getClass(day: string, period: number) {
    return myEntries.find(
      (e) => e.day_of_week === day && Number(e.period) === period
    );
  }

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
        <h2>My Class Roster ({roster.length})</h2>
        {roster.length === 0 ? (
          <p>No students currently assigned to your schedule.</p>
        ) : (
          <table className="dashboard-table">
            <thead>
              <tr>
                <th>Name</th>
                <th>Grade</th>
              </tr>
            </thead>
            <tbody>
              {roster.map((s) => (
                <tr key={s.id}>
                  <td>{s.name}</td>
                  <td>{s.grade}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      <section>
        <h2>My Weekly Schedule</h2>
        <table className="dashboard-table">
          <thead>
            <tr>
              <th>Period</th>
              {DAYS.map((d) => (
                <th key={d} style={{ textTransform: "capitalize" }}>
                  {d}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {PERIODS.map((p) => (
              <tr key={p}>
                <td>{p}</td>
                {DAYS.map((d) => {
                  const cls = getClass(d, p);
                  return <td key={d}>{cls ? cls.subject : ""}</td>;
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    </div>
  );
}