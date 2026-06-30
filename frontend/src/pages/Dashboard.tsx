import { useEffect, useState } from "react";
import { getStudents } from "../api/students";
import { getStaff } from "../api/staff";
import { getSchedule } from "../api/schedule";
import { getComplianceFlags } from "../api/compliance";
import "../components/Dashboard.css";

export default function Dashboard() {
  const [students, setStudents] = useState<any[]>([]);
  const [staff, setStaff] = useState<any[]>([]);
  const [schedule, setSchedule] = useState<any[]>([]);
  const [flags, setFlags] = useState<any[]>([]);

  useEffect(() => {
    load();
  }, []);

  async function load() {
    const [s1, s2, s3, s4] = await Promise.all([
      getStudents(),
      getStaff(),
      getSchedule(),
      getComplianceFlags(),
    ]);

    setStudents(s1 || []);
    setStaff(s2 || []);
    setSchedule(s3 || []);
    setFlags(s4 || []);
  }

  const critical = flags.filter((f) => f.severity === "critical" || f.type === "critical");
  const warnings = flags.filter((f) => f.severity === "warning" || f.type === "warning");

  return (
    <div className="dashboard">

      {/* HEADER */}
      <div className="dashboard-header">
        <h1>School Dashboard</h1>

        <div className="actions">
          <button>🔄 Refresh</button>
          <button>⚙️ Generate Schedule</button>
          <button className="danger">🧹 Reset</button>
        </div>
      </div>

      {/* KPI CARDS */}
      <div className="kpi-grid">

        <div className="kpi-card">
          <div className="kpi-label">Students</div>
          <div className="kpi-value">{students.length}</div>
        </div>

        <div className="kpi-card">
          <div className="kpi-label">Staff</div>
          <div className="kpi-value">{staff.length}</div>
        </div>

        <div className="kpi-card">
          <div className="kpi-label">Schedule Entries</div>
          <div className="kpi-value">{schedule.length}</div>
        </div>

        <div className="kpi-card alert">
          <div className="kpi-label">Critical Issues</div>
          <div className="kpi-value">{critical.length}</div>
        </div>

        <div className="kpi-card warn">
          <div className="kpi-label">Warnings</div>
          <div className="kpi-value">{warnings.length}</div>
        </div>

      </div>

      {/* MAIN GRID */}
      <div className="dashboard-grid">

        {/* ALERT FEED */}
        <div className="panel">
          <h2>🚨 Critical Alerts</h2>

          {critical.length === 0 ? (
            <p className="empty">No critical issues 🎉</p>
          ) : (
            critical.slice(0, 6).map((f, i) => (
              <div key={i} className="alert-item critical">
                <strong>{f.student_name || f.studentName}</strong>
                <p>{f.description || f.message}</p>
              </div>
            ))
          )}
        </div>

        {/* WARNING FEED */}
        <div className="panel">
          <h2>⚠️ Warnings</h2>

          {warnings.length === 0 ? (
            <p className="empty">No warnings</p>
          ) : (
            warnings.slice(0, 6).map((f, i) => (
              <div key={i} className="alert-item warning">
                <strong>{f.student_name || f.studentName}</strong>
                <p>{f.description || f.message}</p>
              </div>
            ))
          )}
        </div>

        {/* QUICK ACTIONS */}
        <div className="panel">
          <h2>⚡ Quick Actions</h2>

          <button className="action-btn">➕ Add Student</button>
          <button className="action-btn">➕ Add Staff</button>
          <button className="action-btn">🔄 Generate Schedule</button>
          <button className="action-btn">📊 Run Compliance Check</button>
        </div>

      </div>

    </div>
  );
}