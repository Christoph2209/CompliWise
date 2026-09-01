// components/RunSelector.tsx// components/RunSelector.tsx
import { useEffect, useState } from "react";
import { getScheduleRuns } from "../api/scheduleRuns";
import type { ScheduleRun } from "../api/scheduleRuns";

interface RunSelectorProps {
  selectedRunId: string | null;
  onChange: (runId: string) => void;
}

export default function RunSelector({ selectedRunId, onChange }: RunSelectorProps) {
  const [runs, setRuns] = useState<ScheduleRun[]>([]);

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

  if (runs.length === 0) return null;

  return (
    <div style={{ marginBottom: "16px" }}>
      <label style={{ marginRight: "10px", fontWeight: "bold" }}>
        Schedule Run:
      </label>
      <select
        value={selectedRunId || ""}
        onChange={(e) => onChange(e.target.value)}
        style={{ padding: "6px 10px", borderRadius: "6px", border: "1px solid #ccc" }}
      >
        {runs.map((r) => (
          <option key={r.id} value={r.id}>
            {r.name || "Unnamed run"} — {new Date(r.created_at).toLocaleString()}
            {" "}({r.entry_count} entries, {r.open_critical_flags} critical flags)
            {r.status === "published" ? " ★ published" : ""}
          </option>
        ))}
      </select>
    </div>
  );
}