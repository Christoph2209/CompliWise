import { useEffect, useState } from "react";
import { Link, Outlet, useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "../context/authContext";

const SIDEBAR_COLLAPSED_KEY = "compliwise:sidebarCollapsed";

type NavItem = {
  to: string;
  label: string;
  icon: React.ReactNode;
  show?: boolean;
};

function Icon({ children }: { children: React.ReactNode }) {
  return (
    <svg
      width="18"
      height="18"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
      strokeLinecap="round"
      strokeLinejoin="round"
      style={{ flexShrink: 0 }}
    >
      {children}
    </svg>
  );
}

const icons = {
  dashboard: (
    <Icon>
      <path d="M3 11.5L12 4l9 7.5" />
      <path d="M5 10v9h5v-5h4v5h5v-9" />
    </Icon>
  ),
  students: (
    <Icon>
      <circle cx="9" cy="8" r="3.2" />
      <path d="M3.5 20c0-3.3 2.5-5.5 5.5-5.5s5.5 2.2 5.5 5.5" />
      <circle cx="17.5" cy="9" r="2.4" />
      <path d="M15.8 14.6c2.2.4 3.7 2.1 3.7 4.4" />
    </Icon>
  ),
  staff: (
    <Icon>
      <path d="M17 20v-2a4 4 0 0 0-4-4H7a4 4 0 0 0-4 4v2" />
      <circle cx="10" cy="7" r="3.5" />
      <path d="M19 20v-1.6c0-1.6-1-3-2.5-3.6" />
      <path d="M15 4.2a3.5 3.5 0 0 1 0 6.6" />
    </Icon>
  ),
  schedules: (
    <Icon>
      <rect x="3" y="5" width="18" height="16" rx="2" />
      <line x1="3" y1="10" x2="21" y2="10" />
      <line x1="8" y1="3" x2="8" y2="7" />
      <line x1="16" y1="3" x2="16" y2="7" />
    </Icon>
  ),
  compliance: (
    <Icon>
      <path d="M12 3l7 3v6c0 4.5-3 7.7-7 9-4-1.3-7-4.5-7-9V6l7-3z" />
      <path d="M9 12l2 2 4-4" />
    </Icon>
  ),
  flex: (
    <Icon>
      <path d="M4 7l8-4 8 4-8 4-8-4z" />
      <path d="M4 12l8 4 8-4" />
      <path d="M4 17l8 4 8-4" />
    </Icon>
  ),
  menu: (
    <Icon>
      <line x1="4" y1="7" x2="20" y2="7" />
      <line x1="4" y1="12" x2="20" y2="12" />
      <line x1="4" y1="17" x2="20" y2="17" />
    </Icon>
  ),
};

export default function AppLayout() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const isAdminOrPrincipal = user?.role === "admin" || user?.role === "principal";

  // Sidebar can be hidden entirely when someone wants the full screen for a
  // dense page (the schedule grid, a wide table). Off by default; the choice
  // is remembered per-browser so it sticks across visits.
  const [collapsed, setCollapsed] = useState(
    () => localStorage.getItem(SIDEBAR_COLLAPSED_KEY) === "1"
  );

  useEffect(() => {
    try {
      localStorage.setItem(SIDEBAR_COLLAPSED_KEY, collapsed ? "1" : "0");
    } catch {
      // localStorage can be unavailable (private browsing, disabled storage) --
      // the toggle still works for the session, it just won't be remembered.
    }
  }, [collapsed]);

  function handleLogout() {
    logout();
    navigate("/login");
  }

  const items: NavItem[] = [
    { to: "/", label: "Dashboard", icon: icons.dashboard },
    { to: "/students", label: "Students", icon: icons.students },
    { to: "/staff", label: "Staff", icon: icons.staff, show: isAdminOrPrincipal },
    { to: "/student-schedules", label: "Schedules", icon: icons.schedules },
    { to: "/teacher-schedules", label: "Teacher Schedules", icon: icons.schedules },
    { to: "/compliance", label: "Compliance", icon: icons.compliance, show: isAdminOrPrincipal },
    { to: "/flex_groups", label: "Flex Groups", icon: icons.flex },
  ];

  return (
    <div style={styles.container}>
      {/* Sidebar */}
      <aside style={collapsed ? styles.sidebarCollapsed : styles.sidebar}>
        <div style={styles.sidebarInner}>
          <div style={styles.brand}>
            <div style={styles.brandMark}>
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
                <path d="M9 11l3 3L22 4" />
                <path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11" />
              </svg>
            </div>
            <span style={styles.brandName}>CompliWise</span>
            <button
              onClick={() => setCollapsed(true)}
              aria-label="Hide menu"
              title="Hide menu"
              style={styles.collapseButton}
            >
              {icons.menu}
            </button>
          </div>

          <nav style={styles.nav}>
            {items
              .filter((item) => item.show !== false)
              .map((item) => {
                const active = location.pathname === item.to;
                return (
                  <Link
                    key={item.to}
                    to={item.to}
                    style={active ? { ...styles.link, ...styles.linkActive } : styles.link}
                  >
                    {item.icon}
                    {item.label}
                  </Link>
                );
              })}
          </nav>

          <button onClick={handleLogout} style={styles.logoutButton}>
            Log out
          </button>
        </div>
      </aside>

      {/* Reopen button -- only rendered once the sidebar is hidden, since the
          one inside the sidebar is clipped away along with everything else. */}
      {collapsed && (
        <button
          onClick={() => setCollapsed(false)}
          aria-label="Show menu"
          title="Show menu"
          style={styles.expandButton}
        >
          {icons.menu}
        </button>
      )}

      {/* Main Content */}
      <main style={styles.main}>
        <Outlet />
      </main>
    </div>
  );
}

const styles: Record<string, React.CSSProperties> = {
  container: {
    display: "flex",
    height: "100vh",
    width: "100vw",
  },
  sidebar: {
    width: "252px",
    flexShrink: 0,
    background: "var(--gradient-sidebar)",
    color: "white",
    padding: "24px 16px",
    boxSizing: "border-box",
    overflow: "hidden",
    transition: "width 0.2s ease, padding 0.2s ease",
  },
  sidebarCollapsed: {
    width: "0px",
    flexShrink: 0,
    background: "var(--gradient-sidebar)",
    color: "white",
    padding: "24px 0",
    boxSizing: "border-box",
    overflow: "hidden",
    transition: "width 0.2s ease, padding 0.2s ease",
  },
  sidebarInner: {
    width: "220px",
    display: "flex",
    flexDirection: "column",
    gap: "24px",
    height: "100%",
  },
  brand: {
    display: "flex",
    alignItems: "center",
    gap: "11px",
    padding: "0 8px",
  },
  collapseButton: {
    marginLeft: "auto",
    width: "28px",
    height: "28px",
    flexShrink: 0,
    background: "rgba(255,255,255,0.12)",
    border: "none",
    borderRadius: "8px",
    color: "white",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    cursor: "pointer",
    padding: 0,
  },
  expandButton: {
    position: "fixed",
    top: "24px",
    left: "24px",
    zIndex: 20,
    width: "40px",
    height: "40px",
    background: "white",
    border: "1px solid var(--border)",
    borderRadius: "10px",
    color: "var(--green-700)",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    cursor: "pointer",
    boxShadow: "0 2px 10px rgba(20, 50, 35, 0.12)",
  },
  brandMark: {
    width: "32px",
    height: "32px",
    borderRadius: "9px",
    background: "rgba(255,255,255,0.16)",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    flexShrink: 0,
  },
  brandName: {
    fontFamily: "var(--font-heading)",
    fontWeight: 800,
    fontSize: "17px",
  },
  nav: {
    display: "flex",
    flexDirection: "column",
    gap: "3px",
  },
  link: {
    display: "flex",
    alignItems: "center",
    gap: "12px",
    color: "rgba(255,255,255,0.85)",
    textDecoration: "none",
    padding: "10px 14px",
    borderRadius: "10px",
    fontSize: "14px",
    fontWeight: 600,
  },
  linkActive: {
    background: "white",
    color: "var(--green-700)",
    fontWeight: 700,
  },
  logoutButton: {
    marginTop: "auto",
    width: "100%",
    padding: "10px",
    background: "transparent",
    color: "#fff",
    border: "1px solid rgba(255,255,255,0.35)",
    borderRadius: "10px",
    cursor: "pointer",
    fontSize: "14px",
    fontFamily: "var(--font-body)",
    fontWeight: 600,
  },
  main: {
    flex: 1,
    padding: "28px 36px",
    background: "var(--bg-page)",
    overflow: "auto",
    boxSizing: "border-box",
  },
};
