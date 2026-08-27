import { BrowserRouter, Routes, Route, useNavigate } from "react-router-dom";
import AppLayout from "./layout/AppLayout";

import TeacherSchedules from "./pages/TeacherSchedule";
import Students from "./pages/Students";
import Staff from "./pages/Staff";
import StudentSchedules from "./pages/StudentSchedules";
import CompliancePage from "./pages/Compliance";
import AuditLogPage from "./pages/AuditLog";
import DashboardRouter from "./pages/DashboardRouter";
import FlexGroups from "./pages/FlexGroups";
import Login from "./pages/LoginPage";
import SetupWizard from "./pages/SetupWizard";
import { AuthProvider } from "./context/authContext";
import ProtectedRoute from "./components/ProtectedRoute";
import RoleRoute from "./components/RoleRoute";
import SetupGate from "./components/SetupGate";

// SetupWizard takes an onComplete callback rather than reading the router
// itself, so it stays usable outside a router context too (e.g. in
// isolation/tests). This is the thin route wrapper that gives it one.
function SetupWizardRoute() {
  const navigate = useNavigate();
  return <SetupWizard onComplete={() => navigate("/login", { replace: true })} />;
}

function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <Routes>
          {/* Not behind SetupGate -- this IS the setup flow. The wizard
              checks /setup/status itself on mount and calls onComplete
              (-> /login) immediately if setup's already done, so hitting
              this route directly after setup is harmless. */}
          <Route path="/setup" element={<SetupWizardRoute />} />

          <Route element={<SetupGate />}>
            <Route path="/login" element={<Login />} />

            <Route
              element={
                <ProtectedRoute>
                  <AppLayout />
                </ProtectedRoute>
              }
            >
              <Route path="/" element={<DashboardRouter />} />
              <Route path="/students" element={<Students />} />
              <Route
                path="/staff"
                element={
                  <RoleRoute allowed={["admin", "principal"]}>
                    <Staff />
                  </RoleRoute>
                }
              />
              <Route path="/student-schedules" element={<StudentSchedules />} />
              <Route path="/teacher-schedules" element={<TeacherSchedules />} />
              <Route
                path="/compliance"
                element={
                  <RoleRoute allowed={["admin", "principal"]}>
                    <CompliancePage />
                  </RoleRoute>
                }
              />
              <Route
                path="/audit-log"
                element={
                  <RoleRoute allowed={["admin"]}>
                    <AuditLogPage />
                  </RoleRoute>
                }
              />
              <Route path="/flex_groups" element={<FlexGroups />} />
            </Route>
          </Route>
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  );
}

export default App;