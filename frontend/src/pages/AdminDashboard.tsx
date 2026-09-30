import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { resetSchedule } from "../api/schedule";
import { loadDashboard, invalidateDashboard } from "../api/dashboardCache";
import { invalidateCache } from "../api/apiCache";
import { useAuth } from "../context/authContext";
import { runComplianceCheck } from "../api/compliance";
import GenerateScheduleModal from "../components/GenerateScheduleModal";
import AddStaffModal from "../components/AddStaffModal";
import AddUserModal from "../components/AddUserModal";
import "../components/Dashboard.css";

export default function Dashboard() {
  const [students, setStudents] = useState<any[]>([]);
  const [staff, setStaff] = useState<any[]>([]);
  const [schedule, setSchedule] = useState<any[]>([]);
  const [flags, setFlags] = useState<any[]>([]);
  const { user } = useAuth();
  const navigate = useNavigate();
  const [showAddUser, setShowAddUser] = useState(false);
  const [showAddStaff, setShowAddStaff] = useState(false);
  const [showGenerateSchedule, setShowGenerateSchedule] = useState(false);

  // Compliance check state
  const [checkingCompliance, setCheckingCompliance] = useState(false);
  const [complianceResult, setComplianceResult] = useState<{
    flags: any[];
    summary: { total_flags: number; critical: number; warnings: number };
  } | null>(null);
  const [complianceError, setComplianceError] = useState<string | null>(null);

  useEffect(() => {
    load();
  }, []);

  // force=true bypasses the cache and hits the API again (Refresh button,
  // and anywhere data was just mutated). force=false (default) serves the
  // cached dashboard instantly if it's still fresh, so revisiting this page
  // doesn't re-fetch everything every time.
  async function load(force = false) {
    const data = await loadDashboard(force);
    setStudents(data.students);
    setStaff(data.staff);
    setSchedule(data.schedule);
    setFlags(data.flags);
  }

  // Call this instead of load() directly after anything that mutates
  // students/staff/schedule/flags server-side, so the next load() actually
  // refetches instead of silently reusing stale cached data.
  async function reloadAfterMutation() {
    invalidateDashboard();
    await load();
  }

  async function handleRunComplianceCheck() {
    setCheckingCompliance(true);
    setComplianceError(null);
    setComplianceResult(null);
    try {
      const result = await runComplianceCheck();
      setComplianceResult(result);
    } catch (err) {
      setComplianceError("Failed to run compliance check");
      console.error(err);
    } finally {
      setCheckingCompliance(false);
    }
  }

  const critical = flags.filter((f) => f.severity === "critical" || f.type === "critical");
  const warnings = flags.filter((f) => f.severity === "warning" || f.type === "warning");
  const isAdmin = user?.role === "admin";

  return (
    <div className="dashboard">

      {/* HEADER */}
      <div className="dashboard-header">
        <h1>School Dashboard</h1>
        <div className="user-info">
        {user ? (
          <>
            <span>
              👤 {user.staff_member
                ? `${user.full_name}`
                : user.full_name || user.id}
                {"\n\n"}
              <span className="role-badge">{user.role}</span>
            </span>
          </>
        ) : (
          <span>Not logged in</span>
        )}
      </div>
        <div className="actions">
          <button onClick={() => load(true)}>🔄 Refresh</button>
          <button onClick={() => setShowGenerateSchedule(true)}>
            ⚙️ Generate Schedule
          </button>
          <button className="danger" onClick={async () => {
            try {
              await resetSchedule();
              alert("Schedule reset successfully!");
              // Reset wipes the schedule for every run, so clear the whole
              // shared cache (StudentSchedules/TeacherSchedules included)
              // rather than just this page's own cached bundle.
              invalidateCache();
              await reloadAfterMutation();
            } catch (error) {
              console.error("Error resetting schedule:", error);
            }
          }}>
            🧹 Reset
          </button>
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
            <div className="alert-scroll-list">
              {critical.map((f, i) => (
                <div
                  key={i}
                  className="alert-item critical alert-item-clickable"
                  role="button"
                  tabIndex={0}
                  onClick={() => navigate("/compliance")}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" || e.key === " ") navigate("/compliance");
                  }}
                >
                  <strong>{f.student_name || f.studentName}</strong>
                  <p>{f.description || f.message}</p>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* WARNING FEED */}
        <div className="panel">
          <h2>⚠️ Warnings</h2>
          {warnings.length === 0 ? (
            <p className="empty">No warnings</p>
          ) : (
            <div className="alert-scroll-list">
              {warnings.map((f, i) => (
                <div
                  key={i}
                  className="alert-item warning alert-item-clickable"
                  role="button"
                  tabIndex={0}
                  onClick={() => navigate("/compliance")}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" || e.key === " ") navigate("/compliance");
                  }}
                >
                  <strong>{f.student_name || f.studentName}</strong>
                  <p>{f.description || f.message}</p>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* QUICK ACTIONS */}
        <div className="panel">
          <h2>⚡ Quick Actions</h2>

          <button className="action-btn">➕ Add Student</button>
          {isAdmin && (
            <button className="action-btn" onClick={() => setShowAddStaff(true)}>
              ➕ Add Staff
            </button>
          )}
          {isAdmin && (
            <button className="action-btn" onClick={() => setShowAddUser(true)}>
              ➕ Add User
            </button>
          )}
          <button className="action-btn" onClick={() => setShowGenerateSchedule(true)}>
            🔄 Generate Schedule
          </button>
          <button
            className="action-btn"
            onClick={handleRunComplianceCheck}
            disabled={checkingCompliance}
          >
            {checkingCompliance ? "Checking..." : "📊 Run Compliance Check"}
          </button>

          {checkingCompliance && (
            <div className="progress-track">
              <div className="progress-bar-indeterminate" />
            </div>
          )}

          {complianceError && (
            <p style={{ color: "var(--red-500)", fontSize: "0.85rem", marginTop: "0.5rem" }}>
              {complianceError}
            </p>
          )}

          {!checkingCompliance && complianceResult && (
            <div className="compliance-result">
              {complianceResult.flags.length === 0 ? (
                <p style={{ color: "var(--green-600)", fontSize: "0.85rem" }}>
                  ✅ No staffing issues found
                </p>
              ) : (
                <>
                  <p style={{ fontSize: "0.85rem", margin: "0.5rem 0" }}>
                    <strong>{complianceResult.summary.critical}</strong> critical,{" "}
                    <strong>{complianceResult.summary.warnings}</strong> warning
                    {complianceResult.summary.warnings === 1 ? "" : "s"}
                  </p>
                  <div style={{ display: "flex", flexDirection: "column", gap: "0.5rem" }}>
                    {complianceResult.flags.map((f, i) => (
                      <div
                        key={i}
                        style={{
                          borderLeft: `3px solid ${f.severity === "critical" ? "var(--red-500)" : "var(--amber-500)"}`,
                          paddingLeft: "0.6rem",
                          fontSize: "0.8rem",
                        }}
                      >
                        <strong>{f.title}</strong>
                        <p style={{ margin: "0.15rem 0 0", color: "var(--text)" }}>{f.description}</p>
                      </div>
                    ))}
                  </div>
                </>
              )}
            </div>
          )}
        </div>

      </div>

      {showAddStaff && (
        <AddStaffModal
          schoolId={user?.school_id || ""}
          onClose={() => setShowAddStaff(false)}
          onCreated={reloadAfterMutation}
        />
      )}
      {showAddUser && (
        <AddUserModal
          schoolId={user?.school_id || ""}
          onClose={() => setShowAddUser(false)}
          onCreated={reloadAfterMutation}
        />
      )}
      {showGenerateSchedule && (
        <GenerateScheduleModal
          onClose={() => setShowGenerateSchedule(false)}
          onGenerated={reloadAfterMutation}
        />
      )}
    </div>
  );
}