import { useAuth } from "../context/authContext";
import AdminDashboard from "./AdminDashboard";
import TeacherDashboard from "./TeacherDashboard";

export default function DashboardRouter() {
  const { user } = useAuth();

  if (!user) return null; // ProtectedRoute should prevent this, but just in case

  switch (user.role) {
    case "admin":
    case "principal":
      return <AdminDashboard />;
    case "teacher":
    case "aide":
      return <TeacherDashboard />;
    default:
      return <TeacherDashboard />;
  }
}