import { BrowserRouter, Routes, Route } from "react-router-dom";
import AppLayout from "./layout/AppLayout";

import TeacherSchedules from "./pages/TeacherSchedule";
import Students from "./pages/Students";
import Staff from "./pages/Staff";
import StudentSchedules from "./pages/StudentSchedules";
import CompliancePage from "./pages/Compliance";
import DashboardRouter from "./pages/DashboardRouter";
import FlexGroups from "./pages/FlexGroups";
import Login from "./pages/LoginPage";
import { AuthProvider } from "./context/authContext";
import ProtectedRoute from "./components/ProtectedRoute";
import RoleRoute from "./components/RoleRoute";

function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <Routes>
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
            <Route path="/flex_groups" element={<FlexGroups />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  );
}

export default App;