import { useEffect, useState } from "react";
import { getAuditLogs, type AuditLogEntry } from "../api/audit";

export default function AuditLogPage() {
  const [logs, setLogs] = useState<AuditLogEntry[]>([]);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function load() {
    try {
      const data = await getAuditLogs();
      setLogs(data || []);
    } catch (err) {
      setError(
        "Failed to load audit logs." +
          (err instanceof Error ? ` Error: ${err.message}` : "")
      );
    }
  }

   useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- fetch-on-mount + polling, load() is async
    load();
    const interval = setInterval(load, 10000);
    return () => clearInterval(interval);
  }, []);

  const getColor = (action: string) => {
    if (action.includes("login")) return "var(--blue-100)";
    if (action.includes("resolve")) return "var(--green-100)";
    if (action.includes("generate")) return "#ece7f7";
    if (action.includes("update")) return "var(--amber-100)";
    return "var(--bg-page)";
  };

  return (
    <div style={{ padding: "28px 36px" }}>
      <h1>Audit Log</h1>

      <p style={{ color: "var(--text)" }}>
        Live data from database (AuditLog table)
      </p>

      {error && (
        <div style={{ background: "var(--red-100)", color: "var(--red-500)", padding: "10px", borderRadius: "10px", marginBottom: "10px" }}>
          {error}
        </div>
      )}

      {logs.length === 0 ? (
        <div style={{ background: "var(--bg-page)", color: "var(--text)", padding: "10px", borderRadius: "10px" }}>
          No audit log entries found
        </div>
      ) : (
        <table style={{ width: "100%", borderSpacing: "0 10px" }}>
          <thead>
            <tr>
              <th align="left">When</th>
              <th align="left">Action</th>
              <th align="left">User</th>
              <th align="left">Entity</th>
              <th align="left">Details</th>
            </tr>
          </thead>

          <tbody>
            {logs.map((log) => {
              const isExpanded = expandedId === log.id;

              return (
                <tr key={log.id} style={{ background: getColor(log.action) }}>
                  <td style={{ padding: "10px", color: "var(--text-h)", whiteSpace: "nowrap" }}>
                    {new Date(log.created_at).toLocaleString()}
                  </td>

                  <td style={{ padding: "10px", color: "var(--text-h)" }}>
                    {log.action}
                  </td>

                  <td style={{ padding: "10px", color: "var(--text-h)" }}>
                    {log.user_name || log.user_email || "—"}
                  </td>

                  <td style={{ padding: "10px", color: "var(--text-h)" }}>
                    {log.entity_type
                      ? `${log.entity_type}${log.entity_id ? ` (${log.entity_id.slice(0, 8)}…)` : ""}`
                      : "—"}
                  </td>

                  <td style={{ padding: "10px" }}>
                    {(log.before_json || log.after_json) && (
                      <button
                        onClick={() =>
                          setExpandedId(isExpanded ? null : log.id)
                        }
                      >
                        {isExpanded ? "Hide" : "View"}
                      </button>
                    )}

                    {isExpanded && (
                      <pre
                        style={{
                          marginTop: "8px",
                          padding: "8px",
                          background: "white",
                          border: "1px solid var(--border)",
                          borderRadius: "8px",
                          fontSize: "12px",
                          maxWidth: "500px",
                          overflowX: "auto",
                        }}
                      >
                        {JSON.stringify(
                          { before: log.before_json, after: log.after_json },
                          null,
                          2
                        )}
                      </pre>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
    </div>
  );
}