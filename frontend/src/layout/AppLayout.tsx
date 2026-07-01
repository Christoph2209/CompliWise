import { Link, Outlet } from "react-router-dom";

export default function AppLayout() {
  return (
    <div style={styles.container}>
      
      {/* Sidebar */}
      <aside style={styles.sidebar}>
        <h2 style={{ marginBottom: 20 }}>CompliWise</h2>

        <nav style={styles.nav}>
          <Link to="/" style={styles.link}>Dashboard</Link>
          <Link to="/students" style={styles.link}>Students</Link>
          <Link to="/staff" style={styles.link}>Staff</Link>
          <Link to="/student-schedules" style={styles.link}>Schedules</Link>
          <Link to="/teacher-schedules" style={styles.link}>Teacher Schedules</Link>
          <Link to="/compliance" style={styles.link}>Compliance</Link>
          <Link to="/flex_groups" style={styles.link}>Flex Groups</Link>
        </nav>
      </aside>

      {/* Main Content */}
      <main style={styles.main}>
        <Outlet />
      </main>

    </div>
  );
}

const styles: any = {
  container: {
    display: "flex",
    height: "100vh",
    width: "100vw",
    fontFamily: "Arial",
  },
  sidebar: {
    width: "240px",
    background: "#111827",
    color: "white",
    padding: "20px",
  },
  nav: {
    display: "flex",
    flexDirection: "column",
    gap: "12px",
  },
  link: {
    color: "#fff",
    textDecoration: "none",
    padding: "8px",
    borderRadius: "6px",
  },
  main: {
    flex: 1,
    padding: "24px",
    background: "#f3f4f6",
    overflow: "auto",
  },
};