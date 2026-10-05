// components/RunSelector.tsx
import { useEffect, useState } from "react";
import { getScheduleRuns, publishScheduleRun } from "../api/scheduleRuns";
import type { ScheduleRun } from "../api/scheduleRuns";
import { invalidateCache } from "../api/apiCache";
import { invalidateDashboard } from "../api/dashboardCache";

interface RunSelectorProps {
  selectedRunId: string | null;
  onChange: (runId: string) => void;
  // Lets the page react to the selected run's status (e.g. lock editing
  // once it's published).
  onSelectedRunChange?: (run: ScheduleRun | null) => void;
}

export default function RunSelector({ selectedRunId, onChange, onSelectedRunChange }: RunSelectorProps) {
  const [runs, setRuns] = useState<ScheduleRun[]>([]);
  const [publishing, setPublishing] = useState(false);
  const [publishError, setPublishError] = useState<string | null>(null);

  useEffect(() => {
    async function load() {
      const data = await getScheduleRuns();
      setRuns(data);

      // Default to the most recent run if nothing selected yet
      if (data.length > 0 && !selectedRunId) {
        onChange(data[0].id);
      }
    }
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const selectedRun = runs.find((r) => r.id === selectedRunId) ?? null;

  useEffect(() => {
    onSelectedRunChange?.(selectedRun);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedRun?.id, selectedRun?.status]);

  async function handlePublish() {
    if (!selectedRun) return;
    const ok = window.confirm(
      "Publish this schedule?\n\n" +
        "It becomes the schedule teachers see. Published schedules are permanent: " +
        "they can't be edited, and Reset won't delete them. To change it later, " +
        "generate a new draft and publish that."
    );
    if (!ok) return;

    setPublishing(true);
    setPublishError(null);
    try {
      const result = await publishScheduleRun(selectedRun.id);
      setRuns((prev) =>
        prev.map((r) => (r.id === selectedRun.id ? { ...r, ...result } : r))
      );
      // Teachers' default schedule just changed, so drop cached copies.
      invalidateCache();
      invalidateDashboard();
    } catch (err: any) {
      setPublishError(err?.response?.data?.detail || "Couldn't publish this schedule. Try again.");
    } finally {
      setPublishing(false);
    }
  }

  if (runs.length === 0) return null;

  return (
    <div style={{ marginBottom: "16px" }}>
      <div style={{ display: "flex", flexWrap: "wrap", alignItems: "center", gap: "10px" }}>
        <label style={{ fontWeight: "bold" }} htmlFor="run-selector">
          Schedule Run:
        </label>
        <select
          id="run-selector"
          value={selectedRunId || ""}
          onChange={(e) => onChange(e.target.value)}
          style={{ padding: "8px 12px", borderRadius: "10px", border: "1.5px solid var(--border)", fontFamily: "var(--font-body)" }}
        >
          {runs.map((r) => (
            <option key={r.id} value={r.id}>
              {r.status === "published" ? "★ Published — " : "Draft — "}
              {r.name || "Unnamed run"} — {new Date(r.created_at).toLocaleString()}
              {" "}({r.entry_count} entries, {r.open_critical_flags} critical flags)
            </option>
          ))}
        </select>

        {selectedRun?.status === "published" ? (
          <span style={{ fontWeight: 600, color: "var(--green-700)" }}>
            ★ Published
            {selectedRun.published_at
              ? ` ${new Date(selectedRun.published_at).toLocaleDateString()}`
              : ""}
            {" "}· locked
          </span>
        ) : (
          selectedRun && (
            <button
              type="button"
              onClick={handlePublish}
              disabled={publishing}
              style={{
                padding: "8px 14px",
                borderRadius: "10px",
                border: "none",
                background: "var(--green-700)",
                color: "white",
                fontWeight: 600,
                cursor: publishing ? "wait" : "pointer",
              }}
            >
              {publishing ? "Publishing…" : "Publish schedule"}
            </button>
          )
        )}
      </div>
      {publishError && (
        <p className="cal-notice" role="alert" style={{ marginTop: "8px" }}>
          {publishError}
        </p>
      )}
    </div>
  );
}
