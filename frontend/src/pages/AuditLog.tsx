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
    if (action.includes("login")) return "#e0f2fe";
    if (action.includes("resolve")) return "#dcfce7";
    if (action.includes("generate")) return "#f3e8ff";
    if (action.includes("update")) return "#fef3c7";
    return "#f3f4f6";
  };

  return (
    <div style={{ padding: "20px", fontFamily: "Arial" }}>
      <h1 style={{ color: "#000000" }}>Audit Log</h1>

      <p style={{ color: "#666" }}>
        Live data from database (AuditLog table)
      </p>

      {error && (
        <div style={{ background: "#fee2e2", padding: "10px", marginBottom: "10px" }}>
          {error}
        </div>
      )}

      {logs.length === 0 ? (
        <div style={{ background: "#f3f4f6", padding: "10px" }}>
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
                  <td style={{ padding: "10px", color: "#000000", whiteSpace: "nowrap" }}>
                    {new Date(log.created_at).toLocaleString()}
                  </td>

                  <td style={{ padding: "10px", color: "#000000" }}>
                    {log.action}
                  </td>

                  <td style={{ padding: "10px", color: "#000000" }}>
                    {log.user_name || log.user_email || "—"}
                  </td>

                  <td style={{ padding: "10px", color: "#000000" }}>
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
                          background: "#ffffff",
                          border: "1px solid #ddd",
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