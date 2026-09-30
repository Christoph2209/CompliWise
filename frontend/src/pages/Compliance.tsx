import { useEffect, useState } from "react";
import { getComplianceFlags, resolveComplianceFlag } from "../api/compliance";

const CACHE_KEY = "compliance_flags_v1";

export default function CompliancePage() {
  const [issues, setIssues] = useState<any[]>([]);
  const [resolvingIds, setResolvingIds] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);

  async function load() {
    const data = await getComplianceFlags();
    const flags = data || [];
    setIssues(flags);
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

  async function handleDismiss(id: string) {
    setResolvingIds((prev) => [...prev, id]);
    setError(null);

    // optimistic removal
    const prevIssues = issues;
    setIssues((prev) => prev.filter((i) => i.id !== id));

    try {
      await resolveComplianceFlag(id);
    } catch (err) {
      // roll back on failure
      setIssues(prevIssues);
      setError("Failed to dismiss flag. Please try again." + (err instanceof Error ? ` Error: ${err.message}` : ""));
    } finally {
      setResolvingIds((prev) => prev.filter((rid) => rid !== id));
    }
  }

  const getColor = (type: string) => {
    if (type === "critical") return "var(--red-100)";
    if (type === "warning") return "var(--amber-100)";
    return "var(--green-100)";
  };

  // Turn a joined schedule_runs record into a human-readable label.
  // `name` is often reused across runs (e.g. every draft called "Full School
  // Schedule"), so always include a short timestamp to disambiguate runs —
  // don't rely on name alone or on the hover tooltip to tell two runs apart.
  function formatRunLabel(run: any) {
    if (!run) return "Unknown run";
    const label = run.name || "Unnamed run";
    if (!run.created_at) return label;
    const d = new Date(run.created_at);
    const stamp = d.toLocaleString(undefined, {
      month: "short",
      day: "numeric",
      hour: "numeric",
      minute: "2-digit",
    });
    return `${label} · ${stamp}`;
  }

  function formatRunTooltip(issue: any) {
    const run = issue.run;
    const parts = [`Run ID: ${issue.run_id}`];
    if (run?.school_year) parts.push(`School year: ${run.school_year}`);
    if (run?.created_at) parts.push(`Created: ${new Date(run.created_at).toLocaleString()}`);
    return parts.join("\n");
  }

  return (
    <div style={{ padding: "28px 36px" }}>
      <h1>Compliance Dashboard</h1>

      <p style={{ color: "var(--text)" }}>
        Live data from database (ComplianceFlag table)
      </p>

      {error && (
        <div style={{ background: "var(--red-100)", color: "var(--red-500)", padding: "10px", borderRadius: "10px", marginBottom: "10px" }}>
          {error}
        </div>
      )}

      {issues.length === 0 ? (
        <div style={{ background: "var(--green-100)", color: "var(--green-700)", padding: "10px", borderRadius: "10px" }}>
          ✅ No compliance issues found
        </div>
      ) : (
        <table style={{ width: "100%", borderSpacing: "0 10px" }}>
          <thead>
            <tr>
              <th align="left">Run</th>
              <th align="left">Student</th>
              <th align="left">Type</th>
              <th align="left">Issue</th>
              <th align="left">Action</th>
            </tr>
          </thead>

          <tbody>
            {issues.map((issue) => (
              <tr
                key={issue.id}
                style={{ background: getColor(issue.severity || issue.flag_type) }}
              >
                <td
                  style={{ padding: "10px", color: "var(--text-h)" }}
                  title={formatRunTooltip(issue)}
                >
                  {formatRunLabel(issue.run)}
                  {issue.run?.status && (
                    <span
                      style={{
                        marginLeft: "6px",
                        fontSize: "0.75em",
                        padding: "2px 6px",
                        borderRadius: "6px",
                        background: issue.run.status === "published" ? "var(--green-100)" : "var(--amber-100)",
                      }}
                    >
                      {issue.run.status}
                    </span>
                  )}
                </td>

                <td style={{ padding: "10px", color: "var(--text-h)" }}>
                  {issue.student_name}
                </td>

                <td style={{ padding: "10px", color: "var(--text-h)" }}>
                  {(issue.severity || issue.flag_type)?.toUpperCase()}
                </td>

                <td style={{ padding: "10px", color: "var(--text-h)" }}>
                  {issue.title ? (
                    <>
                      <strong>{issue.title}</strong>
                      {issue.description ? ` — ${issue.description}` : ""}
                    </>
                  ) : (
                    issue.description
                  )}
                </td>

                <td style={{ padding: "10px" }}>
                  <button
                    onClick={() => handleDismiss(issue.id)}
                    disabled={resolvingIds.includes(issue.id)}
                  >
                    {resolvingIds.includes(issue.id) ? "Dismissing..." : "Dismiss"}
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