import { useState } from "react";

// ─── Color & Design Tokens ───────────────────────────────────────────────────
const C = {
  navy: "#1a2744",
  navyLight: "#243460",
  blue: "#2563eb",
  blueLight: "#dbeafe",
  teal: "#0891b2",
  tealLight: "#cffafe",
  amber: "#d97706",
  amberLight: "#fef3c7",
  green: "#059669",
  greenLight: "#d1fae5",
  red: "#dc2626",
  redLight: "#fee2e2",
  purple: "#7c3aed",
  purpleLight: "#ede9fe",
  gray50: "#f9fafb",
  gray100: "#f3f4f6",
  gray200: "#e5e7eb",
  gray300: "#d1d5db",
  gray400: "#9ca3af",
  gray500: "#6b7280",
  gray600: "#4b5563",
  gray700: "#374151",
  gray800: "#1f2937",
  white: "#ffffff",
};

// ─── Mock Data ────────────────────────────────────────────────────────────────
const STUDENTS = [
  { id: 1, name: "Aaliyah Thompson", grade: "3rd", iep: true, enl: false, mtss: false, services: ["Speech 2x/wk", "OT 1x/wk"], teacher: "Ms. Rivera", scheduled: true },
  { id: 2, name: "Brandon Kowalski", grade: "5th", iep: true, enl: true, mtss: false, services: ["Reading Support 3x/wk", "ENL 2x/wk"], teacher: "Mr. Chen", scheduled: true },
  { id: 3, name: "Camila Reyes", grade: "2nd", iep: false, enl: true, mtss: false, services: ["ENL 3x/wk"], teacher: "Ms. Patel", scheduled: true },
  { id: 4, name: "DeShawn Morris", grade: "4th", iep: true, enl: false, mtss: true, services: ["Math Support 2x/wk", "Counseling 1x/wk"], teacher: "Ms. Rivera", scheduled: false },
  { id: 5, name: "Elena Petrov", grade: "1st", iep: false, enl: false, mtss: true, services: ["Tier 2 Reading"], teacher: "Mr. Johnson", scheduled: true },
  { id: 6, name: "Felix Nguyen", grade: "3rd", iep: true, enl: false, mtss: false, services: ["Speech 3x/wk", "PT 1x/wk"], teacher: "Mr. Chen", scheduled: false },
  { id: 7, name: "Gabrielle Okafor", grade: "5th", iep: false, enl: false, mtss: false, services: [], teacher: "Ms. Patel", scheduled: true },
  { id: 8, name: "Henry Zhao", grade: "2nd", iep: true, enl: true, mtss: false, services: ["Speech 2x/wk", "ENL 2x/wk"], teacher: "Ms. Rivera", scheduled: true },
  { id: 9, name: "Imani Jackson", grade: "4th", iep: false, enl: false, mtss: true, services: ["Tier 3 Math"], teacher: "Mr. Johnson", scheduled: false },
  { id: 10, name: "Jordan Levine", grade: "1st", iep: true, enl: false, mtss: false, services: ["OT 2x/wk", "Counseling 1x/wk"], teacher: "Ms. Patel", scheduled: true },
];

const STAFF = [
  { id: 1, name: "Sarah Kim", role: "Speech-Language Pathologist", caseload: 18, maxCaseload: 20, days: "Mon-Fri", certifications: ["SLP", "ASHA"] },
  { id: 2, name: "Marcus Webb", role: "Occupational Therapist", caseload: 12, maxCaseload: 15, days: "Mon-Thu", certifications: ["OTR/L"] },
  { id: 3, name: "Lisa Fernandez", role: "ENL Specialist", caseload: 22, maxCaseload: 25, days: "Mon-Fri", certifications: ["ENL", "TESOL"] },
  { id: 4, name: "David Park", role: "Special Ed Teacher", caseload: 8, maxCaseload: 10, days: "Mon-Fri", certifications: ["CSE", "Special Ed"] },
  { id: 5, name: "Tamara Scott", role: "School Psychologist", caseload: 30, maxCaseload: 35, days: "Mon-Fri", certifications: ["Psych", "CSE"] },
  { id: 6, name: "Robert Nzinga", role: "Physical Therapist", caseload: 6, maxCaseload: 10, days: "Tue-Thu", certifications: ["PT", "DPT"] },
];

const PROPOSALS = [
  { id: 1, title: "Fall 2025 IEP Block Schedule", status: "pending", students: 24, conflicts: 2, created: "2025-08-15", priority: "IEP First" },
  { id: 2, title: "ENL Pull-Out Optimization", status: "approved", students: 18, conflicts: 0, created: "2025-08-10", priority: "ENL" },
  { id: 3, title: "MTSS Tier 2 Groupings", status: "draft", students: 12, conflicts: 5, created: "2025-08-20", priority: "MTSS" },
  { id: 4, title: "Spring 2025 Full Rebuild", status: "approved", students: 47, conflicts: 0, created: "2025-01-05", priority: "IEP First" },
];

const SERVICE_GAPS = [
  { student: "DeShawn Morris", service: "Math Support", mandated: "2x/wk", scheduled: "0x/wk", gap: "2 sessions", severity: "high" },
  { student: "Felix Nguyen", service: "Speech", mandated: "3x/wk", scheduled: "1x/wk", gap: "2 sessions", severity: "high" },
  { student: "Imani Jackson", service: "Tier 3 Math", mandated: "3x/wk", scheduled: "2x/wk", gap: "1 session", severity: "medium" },
  { student: "Brandon Kowalski", service: "Reading Support", mandated: "3x/wk", scheduled: "3x/wk", gap: "0 sessions", severity: "none" },
];

const SCHEDULE_BLOCKS = {
  Mon: [
    { time: "8:00", label: "IEP - Speech (Kim)", students: ["Aaliyah T.", "Felix N.", "Henry Z."], type: "iep", provider: "S. Kim" },
    { time: "9:00", label: "ENL Group A (Fernandez)", students: ["Brandon K.", "Camila R.", "Henry Z."], type: "enl", provider: "L. Fernandez" },
    { time: "10:00", label: "IEP - OT (Webb)", students: ["Aaliyah T.", "Jordan L."], type: "iep", provider: "M. Webb" },
    { time: "11:00", label: "MTSS Tier 2 (Park)", students: ["Elena P.", "Imani J."], type: "mtss", provider: "D. Park" },
    { time: "1:00", label: "IEP - Counseling (Scott)", students: ["DeShawn M.", "Jordan L."], type: "iep", provider: "T. Scott" },
  ],
  Tue: [
    { time: "8:00", label: "IEP - Speech (Kim)", students: ["Aaliyah T.", "Brandon K."], type: "iep", provider: "S. Kim" },
    { time: "9:30", label: "ENL Group B (Fernandez)", students: ["Camila R."], type: "enl", provider: "L. Fernandez" },
    { time: "10:00", label: "IEP - PT (Nzinga)", students: ["Felix N."], type: "iep", provider: "R. Nzinga" },
    { time: "2:00", label: "MTSS Tier 3 (Park)", students: ["Imani J."], type: "mtss", provider: "D. Park" },
  ],
  Wed: [
    { time: "8:00", label: "IEP - Speech (Kim)", students: ["Felix N.", "Henry Z."], type: "iep", provider: "S. Kim" },
    { time: "9:00", label: "ENL Group A (Fernandez)", students: ["Brandon K.", "Camila R.", "Henry Z."], type: "enl", provider: "L. Fernandez" },
    { time: "11:00", label: "IEP - OT (Webb)", students: ["Jordan L."], type: "iep", provider: "M. Webb" },
  ],
  Thu: [
    { time: "8:00", label: "IEP - Speech (Kim)", students: ["Aaliyah T.", "Brandon K.", "Felix N."], type: "iep", provider: "S. Kim" },
    { time: "10:00", label: "IEP - PT (Nzinga)", students: ["Felix N."], type: "iep", provider: "R. Nzinga" },
    { time: "1:00", label: "MTSS Tier 2 (Park)", students: ["Elena P.", "Imani J."], type: "mtss", provider: "D. Park" },
  ],
  Fri: [
    { time: "8:30", label: "IEP - Speech (Kim)", students: ["Henry Z."], type: "iep", provider: "S. Kim" },
    { time: "9:00", label: "ENL Group B (Fernandez)", students: ["Camila R.", "Brandon K."], type: "enl", provider: "L. Fernandez" },
    { time: "11:00", label: "IEP - Counseling (Scott)", students: ["Jordan L."], type: "iep", provider: "T. Scott" },
  ],
};

// ─── Shared UI Components ─────────────────────────────────────────────────────
const Badge = ({ label, color = "blue", small }) => {
  const colors = {
    blue: { bg: C.blueLight, text: C.blue },
    amber: { bg: C.amberLight, text: C.amber },
    green: { bg: C.greenLight, text: C.green },
    red: { bg: C.redLight, text: C.red },
    purple: { bg: C.purpleLight, text: C.purple },
    teal: { bg: C.tealLight, text: C.teal },
    gray: { bg: C.gray100, text: C.gray600 },
  };
  const { bg, text } = colors[color] || colors.blue;
  return (
    <span style={{
      background: bg, color: text,
      padding: small ? "2px 7px" : "3px 10px",
      borderRadius: 20, fontSize: small ? 11 : 12,
      fontWeight: 600, display: "inline-block", whiteSpace: "nowrap"
    }}>{label}</span>
  );
};

const Card = ({ children, style }) => (
  <div style={{
    background: C.white, borderRadius: 10, border: `1px solid ${C.gray200}`,
    boxShadow: "0 1px 4px rgba(0,0,0,0.06)", padding: 20, ...style
  }}>{children}</div>
);

const StatCard = ({ label, value, sub, color = C.blue, icon }) => (
  <Card style={{ flex: 1, minWidth: 160 }}>
    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
      <div>
        <div style={{ fontSize: 28, fontWeight: 800, color: C.black }}>{value}</div>
        <div style={{ fontSize: 13, fontWeight: 600, color: C.gray700, marginTop: 2 }}>{label}</div>
        {sub && <div style={{ fontSize: 12, color: C.gray400, marginTop: 2 }}>{sub}</div>}
      </div>
      <div style={{ fontSize: 22, opacity: 0.7 }}>{icon}</div>
    </div>
  </Card>
);

const SectionHeader = ({ title, sub, action }) => (
  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 16 }}>
    <div>
      <h2 style={{ margin: 0, fontSize: 18, fontWeight: 700, color: C.black }}>{title}</h2>
      {sub && <p style={{ margin: "4px 0 0", fontSize: 13, color: C.gray500 }}>{sub}</p>}
    </div>
    {action}
  </div>
);

const Btn = ({ children, onClick, variant = "primary", small, disabled }) => {
  const styles = {
    primary: { background: C.blue, color: C.white, border: "none" },
    secondary: { background: C.white, color: C.gray700, border: `1px solid ${C.gray300}` },
    ghost: { background: "transparent", color: C.blue, border: "none" },
    danger: { background: C.red, color: C.white, border: "none" },
    success: { background: C.green, color: C.white, border: "none" },
  };
  return (
    <button onClick={onClick} disabled={disabled} style={{
      ...styles[variant], borderRadius: 7, padding: small ? "5px 12px" : "8px 16px",
      fontSize: small ? 12 : 13, fontWeight: 600, cursor: disabled ? "not-allowed" : "pointer",
      opacity: disabled ? 0.5 : 1, transition: "opacity 0.15s"
    }}>{children}</button>
  );
};

const Input = ({ placeholder, value, onChange, style }) => (
  <input placeholder={placeholder} value={value} onChange={onChange} style={{
    border: `1px solid ${C.gray300}`, borderRadius: 7, padding: "8px 12px",
    fontSize: 13, color: C.gray800, outline: "none", background: C.white, ...style
  }} />
);

// ─── Pages ────────────────────────────────────────────────────────────────────

// Dashboard
const Dashboard = ({ setPage }) => (
  <div>
    <div style={{ marginBottom: 24 }}>
      <h1 style={{ margin: 0, fontSize: 24, fontWeight: 800, color: C.black }}>Dashboard</h1>
      <p style={{ margin: "6px 0 0", color: C.gray500, fontSize: 14 }}>
        School Year 2025–2026 · IEP services scheduled first
      </p>
    </div>

    {/* Alert Banner */}
    <div style={{
      background: C.amberLight, border: `1px solid ${C.amber}`, borderRadius: 10,
      padding: "12px 16px", marginBottom: 20, display: "flex", alignItems: "center", gap: 10
    }}>
      <span style={{ fontSize: 18 }}>⚠️</span>
      <div>
        <strong style={{ color: C.amber, fontSize: 13 }}>3 students have unscheduled IEP services</strong>
        <span style={{ color: C.gray600, fontSize: 13, marginLeft: 8 }}>
          DeShawn Morris, Felix Nguyen, and Imani Jackson require immediate scheduling.
        </span>
      </div>
      <Btn small variant="secondary" onClick={() => setPage("service-gaps")} style={{ marginLeft: "auto" }}>View Gaps</Btn>
    </div>

    {/* Stat Cards */}
    <div style={{ display: "flex", gap: 14, flexWrap: "wrap", marginBottom: 24 }}>
      <StatCard label="Total Students" value={47} sub="Enrolled" icon="🎒" color={C.blue} />
      <StatCard label="IEP Students" value={18} sub="Priority scheduled" icon="📋" color={C.purple} />
      <StatCard label="ENL Students" value={11} sub="Service mandated" icon="🌐" color={C.teal} />
      <StatCard label="MTSS Students" value={14} sub="Interventions active" icon="📈" color={C.amber} />
      <StatCard label="Compliance Rate" value="94%" sub="IEP mandates met" icon="✅" color={C.green} />
      <StatCard label="Service Gaps" value={3} sub="Needs attention" icon="🚨" color={C.red} />
    </div>

    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 20, marginBottom: 20 }}>
      {/* IEP Priority Queue */}
      <Card>
        <SectionHeader title="IEP Priority Queue" sub="Students awaiting schedule placement" action={
          <Btn small variant="ghost" onClick={() => setPage("students")}>View All →</Btn>
        } />
        {STUDENTS.filter(s => s.iep && !s.scheduled).map(s => (
          <div key={s.id} style={{
            display: "flex", alignItems: "center", gap: 10, padding: "10px 0",
            borderBottom: `1px solid ${C.gray100}`
          }}>
            <div style={{
              width: 36, height: 36, borderRadius: "50%", background: C.purpleLight,
              display: "flex", alignItems: "center", justifyContent: "center",
              fontSize: 14, fontWeight: 700, color: C.purple
            }}>{s.name.split(" ").map(n => n[0]).join("")}</div>
            <div style={{ flex: 1 }}>
              <div style={{ fontSize: 13, fontWeight: 600, color: C.gray800 }}>{s.name}</div>
              <div style={{ fontSize: 11, color: C.gray400 }}>{s.grade} · {s.services.join(", ")}</div>
            </div>
            <Badge label="Unscheduled" color="red" small />
          </div>
        ))}
        {STUDENTS.filter(s => s.iep && !s.scheduled).length === 0 && (
          <div style={{ color: C.green, fontSize: 13, textAlign: "center", padding: 20 }}>
            ✅ All IEP students scheduled
          </div>
        )}
      </Card>

      {/* Recent Proposals */}
      <Card>
        <SectionHeader title="Schedule Proposals" sub="Recent activity" action={
          <Btn small variant="ghost" onClick={() => setPage("proposals")}>View All →</Btn>
        } />
        {PROPOSALS.map(p => (
          <div key={p.id} style={{
            display: "flex", alignItems: "center", gap: 10, padding: "10px 0",
            borderBottom: `1px solid ${C.gray100}`
          }}>
            <div style={{ flex: 1 }}>
              <div style={{ fontSize: 13, fontWeight: 600, color: C.gray800 }}>{p.title}</div>
              <div style={{ fontSize: 11, color: C.gray400 }}>{p.students} students · {p.created}</div>
            </div>
            <Badge label={p.status === "approved" ? "Approved" : p.status === "pending" ? "Pending" : "Draft"}
              color={p.status === "approved" ? "green" : p.status === "pending" ? "amber" : "gray"} small />
          </div>
        ))}
      </Card>
    </div>

    {/* Quick actions */}
    <Card>
      <SectionHeader title="Quick Actions" />
      <div style={{ display: "flex", gap: 12, flexWrap: "wrap" }}>
        {[
          { label: "📅 Build New Schedule", page: "proposals", color: C.blue },
          { label: "🔍 Check Compliance", page: "compliance", color: C.purple },
          { label: "👥 Manage Students", page: "students", color: C.teal },
          { label: "🚨 View Service Gaps", page: "service-gaps", color: C.red },
          { label: "📊 Reports", page: "reports", color: C.amber },
          { label: "⚙️ Settings", page: "settings", color: C.gray600 },
        ].map(a => (
          <button key={a.label} onClick={() => setPage(a.page)} style={{
            background: C.gray50, border: `1px solid ${C.gray200}`, borderRadius: 8,
            padding: "10px 16px", fontSize: 13, fontWeight: 600, color: C.gray700,
            cursor: "pointer", transition: "all 0.15s"
          }}>{a.label}</button>
        ))}
      </div>
    </Card>
  </div>
);

// Students Page
const StudentsPage = () => {
  const [search, setSearch] = useState("");
  const [filter, setFilter] = useState("all");
  const [selected, setSelected] = useState(null);

  const filtered = STUDENTS.filter(s => {
    const matchSearch = s.name.toLowerCase().includes(search.toLowerCase());
    const matchFilter = filter === "all" || (filter === "iep" && s.iep) || (filter === "enl" && s.enl) || (filter === "mtss" && s.mtss) || (filter === "unscheduled" && !s.scheduled);
    return matchSearch && matchFilter;
  });

  return (
    <div>
      <SectionHeader title="Students" sub={`${STUDENTS.length} students enrolled · IEP students prioritized`} action={
        <Btn>+ Add Student</Btn>
      } />

      {/* Filters */}
      <div style={{ display: "flex", gap: 10, marginBottom: 16, flexWrap: "wrap" }}>
        <Input placeholder="Search students..." value={search} onChange={e => setSearch(e.target.value)} style={{ width: 220 }} />
        {["all", "iep", "enl", "mtss", "unscheduled"].map(f => (
          <button key={f} onClick={() => setFilter(f)} style={{
            padding: "7px 14px", borderRadius: 7, fontSize: 12, fontWeight: 600,
            background: filter === f ? C.blue : C.gray100,
            color: filter === f ? C.white : C.gray600,
            border: "none", cursor: "pointer"
          }}>{f === "all" ? "All Students" : f.toUpperCase()}</button>
        ))}
      </div>

      <div style={{ display: "grid", gridTemplateColumns: selected ? "1fr 340px" : "1fr", gap: 20 }}>
        {/* Table */}
        <Card style={{ padding: 0, overflow: "hidden" }}>
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
            <thead>
              <tr style={{ background: C.gray50, borderBottom: `1px solid ${C.gray200}` }}>
                {["Student", "Grade", "Services", "Provider", "Status"].map(h => (
                  <th key={h} style={{ padding: "10px 16px", textAlign: "left", fontWeight: 600, color: C.gray600, whiteSpace: "nowrap" }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {filtered.map(s => (
                <tr key={s.id} onClick={() => setSelected(s)} style={{
                  borderBottom: `1px solid ${C.gray100}`, cursor: "pointer",
                  background: selected?.id === s.id ? C.blueLight : "transparent"
                }}>
                  <td style={{ padding: "12px 16px" }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                      <div style={{
                        width: 32, height: 32, borderRadius: "50%",
                        background: s.iep ? C.purpleLight : s.enl ? C.tealLight : C.gray100,
                        display: "flex", alignItems: "center", justifyContent: "center",
                        fontSize: 12, fontWeight: 700, color: s.iep ? C.purple : s.enl ? C.teal : C.gray500
                      }}>{s.name.split(" ").map(n => n[0]).join("")}</div>
                      <div>
                        <div style={{ fontWeight: 600, color: C.gray800 }}>{s.name}</div>
                        <div style={{ display: "flex", gap: 4, marginTop: 2, flexWrap: "wrap" }}>
                          {s.iep && <Badge label="IEP" color="purple" small />}
                          {s.enl && <Badge label="ENL" color="teal" small />}
                          {s.mtss && <Badge label="MTSS" color="amber" small />}
                        </div>
                      </div>
                    </div>
                  </td>
                  <td style={{ padding: "12px 16px", color: C.gray600 }}>{s.grade}</td>
                  <td style={{ padding: "12px 16px", color: C.gray600 }}>{s.services.length > 0 ? s.services.join(", ") : <span style={{ color: C.gray300 }}>None</span>}</td>
                  <td style={{ padding: "12px 16px", color: C.gray600 }}>{s.teacher}</td>
                  <td style={{ padding: "12px 16px" }}>
                    <Badge label={s.scheduled ? "Scheduled" : "Unscheduled"} color={s.scheduled ? "green" : "red"} small />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>

        {/* Detail Panel */}
        {selected && (
          <Card>
            <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 16 }}>
              <h3 style={{ margin: 0, fontSize: 15, fontWeight: 700, color: C.gray800 }}>Student Detail</h3>
              <Btn small variant="ghost" onClick={() => setSelected(null)}>✕</Btn>
            </div>
            <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 16 }}>
              <div style={{
                width: 48, height: 48, borderRadius: "50%",
                background: selected.iep ? C.purpleLight : selected.enl ? C.tealLight : C.gray100,
                display: "flex", alignItems: "center", justifyContent: "center",
                fontSize: 18, fontWeight: 700, color: selected.iep ? C.purple : C.teal
              }}>{selected.name.split(" ").map(n => n[0]).join("")}</div>
              <div>
                <div style={{ fontWeight: 700, fontSize: 15, color: C.gray800 }}>{selected.name}</div>
                <div style={{ fontSize: 12, color: C.gray500 }}>Grade {selected.grade} · {selected.teacher}</div>
              </div>
            </div>
            <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginBottom: 16 }}>
              {selected.iep && <Badge label="IEP" color="purple" />}
              {selected.enl && <Badge label="ENL" color="teal" />}
              {selected.mtss && <Badge label="MTSS" color="amber" />}
              {!selected.iep && !selected.enl && !selected.mtss && <Badge label="General Ed" color="gray" />}
            </div>
            <div style={{ marginBottom: 12 }}>
              <div style={{ fontSize: 11, fontWeight: 700, color: C.gray400, textTransform: "uppercase", letterSpacing: 1, marginBottom: 6 }}>Mandated Services</div>
              {selected.services.length > 0 ? selected.services.map((svc, i) => (
                <div key={i} style={{
                  padding: "6px 10px", background: C.gray50, borderRadius: 6,
                  fontSize: 12, color: C.gray700, marginBottom: 4, display: "flex", alignItems: "center", gap: 6
                }}>
                  <span>📌</span> {svc}
                </div>
              )) : <div style={{ color: C.gray400, fontSize: 12 }}>No mandated services</div>}
            </div>
            <div style={{ marginBottom: 16 }}>
              <div style={{ fontSize: 11, fontWeight: 700, color: C.gray400, textTransform: "uppercase", letterSpacing: 1, marginBottom: 6 }}>Schedule Status</div>
              <Badge label={selected.scheduled ? "✅ All Services Scheduled" : "⚠️ Needs Scheduling"} color={selected.scheduled ? "green" : "red"} />
            </div>
            <div style={{ display: "flex", gap: 8 }}>
              <Btn small>Edit Profile</Btn>
              <Btn small variant="secondary">View Schedule</Btn>
            </div>
          </Card>
        )}
      </div>
    </div>
  );
};

// Staff Page
const StaffPage = () => (
  <div>
    <SectionHeader title="Staff" sub="Service providers and specialists" action={<Btn>+ Add Staff</Btn>} />
    <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(300px, 1fr))", gap: 16 }}>
      {STAFF.map(s => {
        const pct = Math.round((s.caseload / s.maxCaseload) * 100);
        const barColor = pct > 90 ? C.red : pct > 75 ? C.amber : C.green;
        return (
          <Card key={s.id}>
            <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 14 }}>
              <div style={{
                width: 44, height: 44, borderRadius: "50%", background: C.blueLight,
                display: "flex", alignItems: "center", justifyContent: "center",
                fontSize: 16, fontWeight: 700, color: C.blue
              }}>{s.name.split(" ").map(n => n[0]).join("")}</div>
              <div>
                <div style={{ fontWeight: 700, fontSize: 14, color: C.gray800 }}>{s.name}</div>
                <div style={{ fontSize: 12, color: C.gray500 }}>{s.role}</div>
              </div>
            </div>
            <div style={{ marginBottom: 10 }}>
              <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 4 }}>
                <span style={{ fontSize: 12, color: C.gray500 }}>Caseload</span>
                <span style={{ fontSize: 12, fontWeight: 600, color: barColor }}>{s.caseload}/{s.maxCaseload}</span>
              </div>
              <div style={{ height: 6, background: C.gray100, borderRadius: 3, overflow: "hidden" }}>
                <div style={{ height: "100%", width: `${pct}%`, background: barColor, borderRadius: 3 }} />
              </div>
            </div>
            <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginBottom: 12 }}>
              {s.certifications.map(c => <Badge key={c} label={c} color="blue" small />)}
            </div>
            <div style={{ fontSize: 12, color: C.gray400 }}>📅 Available: {s.days}</div>
          </Card>
        );
      })}
    </div>
  </div>
);

// Schedule View
const ScheduleView = () => {
  const [selectedDay, setSelectedDay] = useState("Mon");
  const days = ["Mon", "Tue", "Wed", "Thu", "Fri"];
  const typeColors = { iep: C.purple, enl: C.teal, mtss: C.amber };
  const typeBg = { iep: C.purpleLight, enl: C.tealLight, mtss: C.amberLight };

  return (
    <div>
      <SectionHeader title="Schedule View" sub="Weekly IEP-first service schedule" action={
        <div style={{ display: "flex", gap: 8 }}>
          <Badge label="🟣 IEP" color="purple" />
          <Badge label="🩵 ENL" color="teal" />
          <Badge label="🟡 MTSS" color="amber" />
        </div>
      } />

      {/* Day Tabs */}
      <div style={{ display: "flex", gap: 8, marginBottom: 20 }}>
        {days.map(d => (
          <button key={d} onClick={() => setSelectedDay(d)} style={{
            padding: "8px 20px", borderRadius: 8, border: "none", fontWeight: 600, fontSize: 13,
            background: selectedDay === d ? C.navy : C.gray100,
            color: selectedDay === d ? C.white : C.gray600, cursor: "pointer"
          }}>{d}</button>
        ))}
      </div>

      {/* Time Blocks */}
      <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
        {(SCHEDULE_BLOCKS[selectedDay] || []).map((block, i) => (
          <Card key={i} style={{ borderLeft: `4px solid ${typeColors[block.type]}`, padding: 0, overflow: "hidden" }}>
            <div style={{ display: "flex", alignItems: "stretch" }}>
              <div style={{
                width: 70, background: C.gray50, display: "flex", alignItems: "center",
                justifyContent: "center", padding: "14px 10px",
                borderRight: `1px solid ${C.gray200}`, fontSize: 13, fontWeight: 700, color: C.gray600
              }}>{block.time}</div>
              <div style={{ flex: 1, padding: "14px 16px" }}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
                  <div>
                    <div style={{ fontWeight: 700, fontSize: 14, color: C.gray800 }}>{block.label}</div>
                    <div style={{ fontSize: 12, color: C.gray500, marginTop: 2 }}>Provider: {block.provider}</div>
                  </div>
                  <Badge label={block.type.toUpperCase()} color={block.type === "iep" ? "purple" : block.type === "enl" ? "teal" : "amber"} small />
                </div>
                <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginTop: 10 }}>
                  {block.students.map(st => (
                    <span key={st} style={{
                      background: typeBg[block.type], color: typeColors[block.type],
                      padding: "3px 9px", borderRadius: 20, fontSize: 11, fontWeight: 600
                    }}>{st}</span>
                  ))}
                </div>
              </div>
            </div>
          </Card>
        ))}
      </div>
    </div>
  );
};

// Schedule Proposals
const ProposalsPage = () => {
  const [proposals, setProposals] = useState(PROPOSALS);
  return (
    <div>
      <SectionHeader title="Schedule Proposals" sub="Generate and review automated schedule proposals" action={
        <Btn>+ New Proposal</Btn>
      } />
      <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
        {proposals.map(p => (
          <Card key={p.id}>
            <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
              <div style={{ flex: 1 }}>
                <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 4 }}>
                  <span style={{ fontWeight: 700, fontSize: 15, color: C.gray800 }}>{p.title}</span>
                  <Badge label={p.status === "approved" ? "Approved" : p.status === "pending" ? "Pending Review" : "Draft"}
                    color={p.status === "approved" ? "green" : p.status === "pending" ? "amber" : "gray"} small />
                  <Badge label={p.priority} color="purple" small />
                </div>
                <div style={{ fontSize: 12, color: C.gray500 }}>
                  {p.students} students · Created {p.created} ·{" "}
                  {p.conflicts > 0
                    ? <span style={{ color: C.red, fontWeight: 600 }}>⚠️ {p.conflicts} conflicts</span>
                    : <span style={{ color: C.green, fontWeight: 600 }}>✅ No conflicts</span>}
                </div>
              </div>
              <div style={{ display: "flex", gap: 8 }}>
                <Btn small variant="secondary">View</Btn>
                {p.status !== "approved" && <Btn small variant="success">Approve</Btn>}
              </div>
            </div>
          </Card>
        ))}
      </div>
    </div>
  );
};

// Schedule Checker
const ScheduleCheckerPage = () => {
  const [checked, setChecked] = useState(false);
  return (
    <div>
      <SectionHeader title="Schedule Checker" sub="Verify IEP compliance and detect conflicts before publishing" />
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 20 }}>
        <Card>
          <h3 style={{ margin: "0 0 16px", fontSize: 15, fontWeight: 700, color: C.gray800 }}>Run Compliance Check</h3>
          <p style={{ fontSize: 13, color: C.gray500, marginBottom: 16 }}>
            The schedule checker validates all IEP mandates, checks for provider conflicts, and ensures no student has overlapping service times.
          </p>
          <div style={{ display: "flex", flexDirection: "column", gap: 8, marginBottom: 20 }}>
            {["Verify all IEP service minutes", "Check provider availability conflicts", "Validate ENL frequency requirements", "Confirm MTSS grouping eligibility", "Detect student time overlaps"].map(item => (
              <div key={item} style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 13, color: C.gray600 }}>
                <span style={{ color: C.blue }}>○</span> {item}
              </div>
            ))}
          </div>
          <Btn onClick={() => setChecked(true)}>▶ Run Check</Btn>
        </Card>
        <Card>
          <h3 style={{ margin: "0 0 16px", fontSize: 15, fontWeight: 700, color: C.gray800 }}>Check Results</h3>
          {!checked ? (
            <div style={{ color: C.gray300, textAlign: "center", padding: 40, fontSize: 14 }}>Run a check to see results</div>
          ) : (
            <div>
              <div style={{ background: C.greenLight, border: `1px solid ${C.green}`, borderRadius: 8, padding: 12, marginBottom: 10, fontSize: 13, color: C.green }}>
                ✅ IEP service minutes verified for 15/18 students
              </div>
              <div style={{ background: C.redLight, border: `1px solid ${C.red}`, borderRadius: 8, padding: 12, marginBottom: 10, fontSize: 13, color: C.red }}>
                ❌ DeShawn Morris — Math Support: 0 of 2 required sessions scheduled
              </div>
              <div style={{ background: C.redLight, border: `1px solid ${C.red}`, borderRadius: 8, padding: 12, marginBottom: 10, fontSize: 13, color: C.red }}>
                ❌ Felix Nguyen — Speech: only 1 of 3 required sessions scheduled
              </div>
              <div style={{ background: C.amberLight, border: `1px solid ${C.amber}`, borderRadius: 8, padding: 12, marginBottom: 10, fontSize: 13, color: C.amber }}>
                ⚠️ Imani Jackson — Tier 3 Math: 2 of 3 sessions scheduled
              </div>
              <div style={{ background: C.greenLight, border: `1px solid ${C.green}`, borderRadius: 8, padding: 12, fontSize: 13, color: C.green }}>
                ✅ No provider conflicts detected
              </div>
            </div>
          )}
        </Card>
      </div>
    </div>
  );
};

// Compliance
const CompliancePage = () => (
  <div>
    <SectionHeader title="Compliance" sub="IEP mandate tracking and regulatory compliance" />
    <div style={{ display: "flex", gap: 14, flexWrap: "wrap", marginBottom: 24 }}>
      <StatCard label="IEP Compliance" value="94%" sub="15 of 18 fully met" icon="📋" color={C.green} />
      <StatCard label="ENL Compliance" value="100%" sub="All ENL mandates met" icon="🌐" color={C.green} />
      <StatCard label="MTSS Compliance" value="85%" sub="11 of 13 active" icon="📈" color={C.amber} />
      <StatCard label="Open Violations" value={2} sub="Require action" icon="⚖️" color={C.red} />
    </div>
    <Card>
      <SectionHeader title="Compliance by Student" />
      <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
        <thead>
          <tr style={{ background: C.gray50 }}>
            {["Student", "Type", "Required Services", "Scheduled", "Compliance", "Action"].map(h => (
              <th key={h} style={{ padding: "10px 14px", textAlign: "left", fontWeight: 600, color: C.gray600 }}>{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {STUDENTS.filter(s => s.iep || s.enl || s.mtss).map(s => {
            const compliant = s.scheduled;
            return (
              <tr key={s.id} style={{ borderBottom: `1px solid ${C.gray100}` }}>
                <td style={{ padding: "12px 14px", fontWeight: 600, color: C.gray800 }}>{s.name}</td>
                <td style={{ padding: "12px 14px" }}>
                  {s.iep && <Badge label="IEP" color="purple" small />}
                  {s.enl && <Badge label="ENL" color="teal" small />}
                  {s.mtss && <Badge label="MTSS" color="amber" small />}
                </td>
                <td style={{ padding: "12px 14px", color: C.gray600 }}>{s.services.length > 0 ? s.services.join(", ") : "—"}</td>
                <td style={{ padding: "12px 14px" }}><Badge label={s.scheduled ? "Yes" : "No"} color={s.scheduled ? "green" : "red"} small /></td>
                <td style={{ padding: "12px 14px" }}><Badge label={compliant ? "✅ Met" : "❌ Violation"} color={compliant ? "green" : "red"} small /></td>
                <td style={{ padding: "12px 14px" }}>{!compliant && <Btn small>Schedule Now</Btn>}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </Card>
  </div>
);

// Service Gaps
const ServiceGapsPage = () => (
  <div>
    <SectionHeader title="Service Gaps" sub="Students with unmet IEP service requirements" />
    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      {SERVICE_GAPS.map((g, i) => (
        <Card key={i} style={{ borderLeft: `4px solid ${g.severity === "high" ? C.red : g.severity === "medium" ? C.amber : C.green}` }}>
          <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
            <div style={{ flex: 1 }}>
              <div style={{ display: "flex", gap: 10, alignItems: "center", marginBottom: 4 }}>
                <span style={{ fontWeight: 700, fontSize: 14, color: C.gray800 }}>{g.student}</span>
                <Badge label={g.service} color="blue" small />
                {g.severity !== "none" && <Badge label={g.severity === "high" ? "⚠️ High Priority" : "Medium"} color={g.severity === "high" ? "red" : "amber"} small />}
              </div>
              <div style={{ fontSize: 12, color: C.gray500 }}>
                Mandated: <strong>{g.mandated}</strong> · Scheduled: <strong style={{ color: g.gap !== "0 sessions" ? C.red : C.green }}>{g.scheduled}</strong> · Gap: {g.gap}
              </div>
            </div>
            {g.severity !== "none" && <Btn small>Resolve</Btn>}
            {g.severity === "none" && <Badge label="✅ Satisfied" color="green" />}
          </div>
        </Card>
      ))}
    </div>
  </div>
);

// Reports
const ReportsPage = () => (
  <div>
    <SectionHeader title="Reports" sub="Generate compliance and scheduling reports" action={<Btn>Export PDF</Btn>} />
    <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(260px, 1fr))", gap: 16 }}>
      {[
        { title: "IEP Services Summary", desc: "All mandated vs. scheduled services by student", icon: "📋", color: C.purple },
        { title: "Staff Caseload Report", desc: "Provider utilization and availability overview", icon: "👥", color: C.blue },
        { title: "Compliance Audit", desc: "Full audit trail of service delivery for the year", icon: "⚖️", color: C.red },
        { title: "Service Gap Analysis", desc: "Students with unmet IEP minutes and gap details", icon: "🚨", color: C.amber },
        { title: "Schedule Efficiency", desc: "Grouping optimization and time utilization stats", icon: "⏱️", color: C.teal },
        { title: "ENL Progress Tracker", desc: "ENL service frequency and attendance tracking", icon: "🌐", color: C.green },
      ].map(r => (
        <Card key={r.title} style={{ cursor: "pointer" }}>
          <div style={{ fontSize: 28, marginBottom: 10 }}>{r.icon}</div>
          <div style={{ fontWeight: 700, fontSize: 14, color: C.gray800, marginBottom: 4 }}>{r.title}</div>
          <div style={{ fontSize: 12, color: C.gray500, marginBottom: 14 }}>{r.desc}</div>
          <Btn small variant="secondary">Generate</Btn>
        </Card>
      ))}
    </div>
  </div>
);

// Flex Group Builder
const FlexGroupBuilderPage = () => (
  <div>
    <SectionHeader title="Flex Group Builder" sub="What I Need — build individualized intervention plans" action={<Btn>+ New Flex Group Plan</Btn>} />
    <Card>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 20 }}>
        <div>
          <h3 style={{ margin: "0 0 12px", fontSize: 14, fontWeight: 700, color: C.gray700 }}>Select Student</h3>
          <select style={{ width: "100%", padding: "8px 12px", borderRadius: 7, border: `1px solid ${C.gray300}`, fontSize: 13, marginBottom: 16 }}>
            {STUDENTS.filter(s => s.iep || s.mtss).map(s => <option key={s.id}>{s.name}</option>)}
          </select>
          <h3 style={{ margin: "0 0 12px", fontSize: 14, fontWeight: 700, color: C.gray700 }}>Goal Areas</h3>
          {["Reading Fluency", "Math Computation", "Written Expression", "Social/Emotional", "Speech/Language", "Motor Skills"].map(g => (
            <label key={g} style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 13, color: C.gray600, marginBottom: 8, cursor: "pointer" }}>
              <input type="checkbox" style={{ accentColor: C.blue }} /> {g}
            </label>
          ))}
        </div>
        <div>
          <h3 style={{ margin: "0 0 12px", fontSize: 14, fontWeight: 700, color: C.gray700 }}>Intervention Plan</h3>
          <textarea placeholder="Enter individualized plan details, goals, and strategies..." style={{
            width: "100%", height: 200, padding: 12, borderRadius: 7, border: `1px solid ${C.gray300}`,
            fontSize: 13, resize: "vertical", fontFamily: "inherit", boxSizing: "border-box"
          }} />
          <div style={{ marginTop: 12, display: "flex", gap: 8 }}>
            <Btn>Save Flex Group Plan</Btn>
            <Btn variant="secondary">Preview</Btn>
          </div>
        </div>
      </div>
    </Card>
  </div>
);

// Cascading Coverage
const CascadingPage = () => (
  <div>
    <SectionHeader title="Cascading Coverage" sub="Automatic substitute coverage when a provider is absent" />
    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 20 }}>
      <Card>
        <h3 style={{ margin: "0 0 16px", fontSize: 14, fontWeight: 700, color: C.gray700 }}>Report Absence</h3>
        <div style={{ marginBottom: 12 }}>
          <label style={{ fontSize: 12, fontWeight: 600, color: C.gray500, display: "block", marginBottom: 4 }}>Provider</label>
          <select style={{ width: "100%", padding: "8px 12px", borderRadius: 7, border: `1px solid ${C.gray300}`, fontSize: 13 }}>
            {STAFF.map(s => <option key={s.id}>{s.name} — {s.role}</option>)}
          </select>
        </div>
        <div style={{ marginBottom: 16 }}>
          <label style={{ fontSize: 12, fontWeight: 600, color: C.gray500, display: "block", marginBottom: 4 }}>Date</label>
          <Input type="date" style={{ width: "100%", boxSizing: "border-box" }} />
        </div>
        <Btn>Find Coverage</Btn>
      </Card>
      <Card>
        <h3 style={{ margin: "0 0 16px", fontSize: 14, fontWeight: 700, color: C.gray700 }}>Coverage Queue</h3>
        <div style={{ color: C.gray400, textAlign: "center", padding: 30, fontSize: 13 }}>
          No active coverage requests.<br />
          <span style={{ fontSize: 12 }}>IEP sessions are always prioritized for substitute coverage.</span>
        </div>
      </Card>
    </div>
  </div>
);

// Legal Library
const LegalLibraryPage = () => (
  <div>
    <SectionHeader title="Legal Library" sub="IDEA, ENL, and MTSS regulatory references" />
    <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
      {[
        { title: "IDEA 2004 — IEP Service Requirements", category: "Federal", desc: "Mandates for IEP development, service frequency, and placement decisions under the Individuals with Disabilities Education Act." },
        { title: "Part B Regulations — Free Appropriate Public Education (FAPE)", category: "Federal", desc: "Requirements ensuring students with disabilities receive education and services at no cost to families." },
        { title: "New York State ENL Regulations (CR Part 154)", category: "State", desc: "Commissioner's Regulations governing English as a New Language services, frequency requirements, and staffing qualifications." },
        { title: "MTSS Framework — NYS Guidance", category: "State", desc: "Multi-Tiered System of Supports guidelines including Tier 1/2/3 intervention criteria and progress monitoring." },
        { title: "Procedural Safeguards Notice", category: "Federal", desc: "Parent rights under IDEA including prior written notice, consent requirements, and dispute resolution." },
      ].map(doc => (
        <Card key={doc.title}>
          <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
            <div style={{ fontSize: 24 }}>📄</div>
            <div style={{ flex: 1 }}>
              <div style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 3 }}>
                <span style={{ fontWeight: 700, fontSize: 13, color: C.gray800 }}>{doc.title}</span>
                <Badge label={doc.category} color={doc.category === "Federal" ? "blue" : "teal"} small />
              </div>
              <div style={{ fontSize: 12, color: C.gray500 }}>{doc.desc}</div>
            </div>
            <Btn small variant="secondary">View</Btn>
          </div>
        </Card>
      ))}
    </div>
  </div>
);

// Settings
const SettingsPage = () => (
  <div>
    <SectionHeader title="Settings" sub="School configuration and scheduling rules" />
    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 20 }}>
      {[
        {
          title: "School Information", fields: [
            { label: "School Name", value: "Lincoln Elementary School" },
            { label: "District", value: "Westchester USD" },
            { label: "School Year", value: "2025–2026" },
            { label: "Principal", value: "Dr. Andrea Brooks" },
          ]
        },
        {
          title: "Scheduling Rules", fields: [
            { label: "IEP Priority", value: "Always scheduled first" },
            { label: "Max Group Size (IEP)", value: "4 students" },
            { label: "Min Service Gap", value: "24 hours between sessions" },
            { label: "Auto-Conflict Detection", value: "Enabled" },
          ]
        },
      ].map(section => (
        <Card key={section.title}>
          <h3 style={{ margin: "0 0 16px", fontSize: 14, fontWeight: 700, color: C.gray700 }}>{section.title}</h3>
          {section.fields.map(f => (
            <div key={f.label} style={{ marginBottom: 12 }}>
              <label style={{ fontSize: 11, fontWeight: 700, color: C.gray400, textTransform: "uppercase", letterSpacing: 1, display: "block", marginBottom: 4 }}>{f.label}</label>
              <Input value={f.value} onChange={() => {}} style={{ width: "100%", boxSizing: "border-box" }} />
            </div>
          ))}
          <Btn small>Save Changes</Btn>
        </Card>
      ))}
    </div>
  </div>
);

// ─── Navigation ───────────────────────────────────────────────────────────────
const NAV_ITEMS = [
  { id: "dashboard", label: "Dashboard", icon: "🏠" },
  { id: "students", label: "Students", icon: "🎒" },
  { id: "staff", label: "Staff", icon: "👥" },
  { id: "schedule-view", label: "Schedule View", icon: "📅" },
  { id: "proposals", label: "Schedule Proposals", icon: "📝" },
  { id: "schedule-checker", label: "Schedule Checker", icon: "✅" },
  { id: "compliance", label: "Compliance", icon: "⚖️" },
  { id: "service-gaps", label: "Service Gaps", icon: "🚨" },
  { id: "flex-group-builder", label: "Flex Group Builder", icon: "🌟" },
  { id: "cascading", label: "Cascading Coverage", icon: "🔄" },
  { id: "reports", label: "Reports", icon: "📊" },
  { id: "legal-library", label: "Legal Library", icon: "📚" },
  { id: "settings", label: "Settings", icon: "⚙️" },
];

// ─── App Root ─────────────────────────────────────────────────────────────────
export default function App() {
  const [page, setPage] = useState("dashboard");
  const [sidebarOpen, setSidebarOpen] = useState(true);

  const pageMap = {
    "dashboard": <Dashboard setPage={setPage} />,
    "students": <StudentsPage />,
    "staff": <StaffPage />,
    "schedule-view": <ScheduleView />,
    "proposals": <ProposalsPage />,
    "schedule-checker": <ScheduleCheckerPage />,
    "compliance": <CompliancePage />,
    "service-gaps": <ServiceGapsPage />,
    "flex-group-builder": <FlexGroupBuilderPage />,
    "cascading": <CascadingPage />,
    "reports": <ReportsPage />,
    "legal-library": <LegalLibraryPage />,
    "settings": <SettingsPage />,
  };

  return (
    <div style={{ display: "flex", height: "100vh", fontFamily: "'Inter', system-ui, sans-serif", background: C.gray50 }}>
      {/* Sidebar */}
      <div style={{
        width: sidebarOpen ? 228 : 0, minWidth: sidebarOpen ? 228 : 0,
        background: C.navy, overflowY: "auto", overflowX: "hidden",
        transition: "all 0.2s", display: "flex", flexDirection: "column",
        boxShadow: "2px 0 8px rgba(0,0,0,0.12)"
      }}>
        {/* Logo */}
        <div style={{ padding: "20px 16px 16px", borderBottom: `1px solid ${C.navyLight}` }}>
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <div style={{
              width: 32, height: 32, borderRadius: 8, background: C.blue,
              display: "flex", alignItems: "center", justifyContent: "center",
              fontSize: 16, fontWeight: 800, color: C.white
            }}>C</div>
            <div>
              <div style={{ color: C.white, fontWeight: 800, fontSize: 15 }}>CompliWise</div>
              <div style={{ color: C.gray400, fontSize: 10 }}>IEP-First Scheduling</div>
            </div>
          </div>
        </div>

        {/* Nav Items */}
        <nav style={{ flex: 1, padding: "10px 0" }}>
          {NAV_ITEMS.map(item => {
            const active = page === item.id;
            const isGap = item.id === "service-gaps";
            return (
              <button key={item.id} onClick={() => setPage(item.id)} style={{
                display: "flex", alignItems: "center", gap: 10, width: "100%",
                padding: "9px 16px", border: "none", textAlign: "left",
                background: active ? C.navyLight : "transparent",
                color: active ? C.white : C.gray400,
                cursor: "pointer", fontSize: 13, fontWeight: active ? 600 : 400,
                borderLeft: active ? `3px solid ${C.blue}` : "3px solid transparent",
                transition: "all 0.15s"
              }}>
                <span style={{ fontSize: 14, minWidth: 18 }}>{item.icon}</span>
                <span style={{ flex: 1 }}>{item.label}</span>
                {isGap && <span style={{ background: C.red, color: C.white, borderRadius: 10, fontSize: 10, padding: "1px 6px", fontWeight: 700 }}>3</span>}
              </button>
            );
          })}
        </nav>

        {/* Footer */}
        <div style={{ padding: "12px 16px", borderTop: `1px solid ${C.navyLight}` }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <div style={{
              width: 28, height: 28, borderRadius: "50%", background: C.blue,
              display: "flex", alignItems: "center", justifyContent: "center",
              fontSize: 11, fontWeight: 700, color: C.white
            }}>AB</div>
            <div>
              <div style={{ color: C.white, fontSize: 12, fontWeight: 600 }}>Dr. A. Brooks</div>
              <div style={{ color: C.gray400, fontSize: 10 }}>Administrator</div>
            </div>
          </div>
        </div>
      </div>

      {/* Main */}
      <div style={{ flex: 1, display: "flex", flexDirection: "column", overflow: "hidden" }}>
        {/* Top Bar */}
        <div style={{
          height: 52, background: C.white, borderBottom: `1px solid ${C.gray200}`,
          display: "flex", alignItems: "center", padding: "0 20px", gap: 12,
          boxShadow: "0 1px 3px rgba(0,0,0,0.05)"
        }}>
          <button onClick={() => setSidebarOpen(o => !o)} style={{
            background: "none", border: "none", cursor: "pointer", fontSize: 18, color: C.gray500
          }}>☰</button>
          <div style={{ flex: 1, fontSize: 14, fontWeight: 600, color: C.gray700 }}>
            {NAV_ITEMS.find(n => n.id === page)?.label || "CompliWise"}
          </div>
          <Badge label="SY 2025–2026" color="blue" />
          <Badge label="IEP First ✓" color="purple" />
        </div>

        {/* Page Content */}
        <div style={{ flex: 1, overflowY: "auto", padding: 24 }}>
          {pageMap[page] || <div style={{ color: C.gray400 }}>Page not found</div>}
        </div>
      </div>
    </div>
  );
}
