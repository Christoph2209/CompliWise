import { useEffect, useState } from "react";
import { getComplianceFlags } from "../api/compliance";

const CACHE_KEY = "compliance_flags_v1";

export default function CompliancePage() {
  const [issues, setIssues] = useState<any[]>([]);
  const [dismissed, setDismissed] = useState<string[]>([]);

  async function load() {
    const data = await getComplianceFlags();

    const flags = data || [];

    setIssues(flags);

    // cache only for offline fallback
    localStorage.setItem(CACHE_KEY, JSON.stringify(flags));
  }

  useEffect(() => {
    const cached = localStorage.getItem(CACHE_KEY);

    if (cached) {
      setIssues(JSON.parse(cached));
    }

    load();

    const interval = setInterval(load, 10000);
    return () => clearInterval(interval);
  }, []);

  const visibleIssues = issues.filter(
    (i) => !dismissed.includes(i.id)
  );

  const getColor = (type: string) => {
    if (type === "critical") return "#fee2e2";
    if (type === "warning") return "#fef3c7";
    return "#dcfce7";
  };

  return (
    <div style={{ padding: "20px", fontFamily: "Arial" }}>
      <h1>Compliance Dashboard</h1>

      <p style={{ color: "#666" }}>
        Live data from database (ComplianceFlag table)
      </p>

      {visibleIssues.length === 0 ? (
        <div style={{ background: "#dcfce7", padding: "10px" }}>
          ✅ No compliance issues found
        </div>
      ) : (
        <table style={{ width: "100%", borderSpacing: "0 10px" }}>
          <thead>
            <tr>
              <th align="left">Student</th>
              <th align="left">Type</th>
              <th align="left">Issue</th>
              <th align="left">Action</th>
            </tr>
          </thead>

          <tbody>
            {visibleIssues.map((issue) => (
              <tr
                key={issue.id}
                style={{ background: getColor(issue.severity || issue.type) }}
              >
                <td style={{ padding: "10px" }}>
                  {issue.student_name}
                </td>

                <td style={{ padding: "10px" }}>
                  {(issue.severity || issue.type)?.toUpperCase()}
                </td>

                <td style={{ padding: "10px" }}>
                  {issue.description || issue.message}
                </td>

                <td style={{ padding: "10px" }}>
                  <button
                    onClick={() =>
                      setDismissed([...dismissed, issue.id])
                    }
                  >
                    Dismiss
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}