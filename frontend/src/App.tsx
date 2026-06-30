import { BrowserRouter, Routes, Route } from "react-router-dom";
import AppLayout from "./layout/AppLayout";

import TeacherSchedules from "./pages/TeacherSchedule";
import Students from "./pages/Students";
import Staff from "./pages/Staff";
import StudentSchedules from "./pages/StudentSchedules";
import CompliancePage from "./pages/Compliance";
import Dashboard from "./pages/Dashboard";
import FlexGroups from "./pages/FlexGroups";

function App() {
  return (
    <BrowserRouter>
      <Routes>
        
        <Route element={<AppLayout />}>
          <Route path="/students" element={<Students />} />
          <Route path="/staff" element={<Staff />} />
          <Route path="/student-schedules" element={<StudentSchedules />} />
          <Route path="/teacher-schedules" element={<TeacherSchedules />} />
          <Route path="/compliance" element={<CompliancePage />} />
          <Route path="/flex_groups" element={<FlexGroups />} />
          <Route path="/" element={<Dashboard />} />
        </Route>

      </Routes>
    </BrowserRouter>
  );
}

export default App;