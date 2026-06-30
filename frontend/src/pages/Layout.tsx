import { Link, Outlet } from "react-router-dom";

export default function Layout() {
  return (
    <div style={styles.container}>
      {/* Sidebar */}
      <div style={styles.sidebar}>
        <h2 style={{ color: "white" }}>DMScheduler</h2>

        <nav style={styles.nav}>
          <Link style={styles.link} to="/">
            📊 Dashboard
          </Link>

          <Link style={styles.link} to="/students">
            👨‍🎓 Students
          </Link>

          <Link style={styles.link} to="/staff">
            👩‍🏫 Staff
          </Link>

          <Link style={styles.link} to="/student-schedules">
            📅 Schedules
          </Link>

          <Link style={styles.link} to="/compliance">
            ⚠️ Compliance
          </Link>
        </nav>
      </div>

      {/* Main content */}
      <div style={styles.main}>
        <Outlet />
      </div>
    </div>
  );
}

const styles: Record<string, React.CSSProperties> = {
  container: {
    display: "flex",
    height: "100vh",
  },

  sidebar: {
    width: "240px",
    backgroundColor: "#111827",
    padding: "20px",
    color: "white",
  },

  nav: {
    display: "flex",
    flexDirection: "column",
    gap: "12px",
    marginTop: "20px",
  },

  link: {
    color: "#e5e7eb",
    textDecoration: "none",
    padding: "8px",
    borderRadius: "6px",
  },

  main: {
    flex: 1,
    padding: "20px",
    overflowY: "auto",
    backgroundColor: "#f9fafb",
  },
};