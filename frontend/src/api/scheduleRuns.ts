import {api} from "./clients";

export interface ScheduleRun {
  id: string;
  name: string;
  school_year: string;
  status: string;
  created_at: string;
  published_at: string | null;
  entry_count: number;
  open_critical_flags: number;
}

export async function getScheduleRuns(): Promise<ScheduleRun[]> {
  const res = await api.get("/schedule-runs");
  return res.data;
}

// Makes a draft run permanent: teachers see it, and it can no longer be
// edited. Only Reset (which wipes every run) removes it.
export async function publishScheduleRun(
  runId: string
): Promise<Pick<ScheduleRun, "id" | "status" | "published_at">> {
  const res = await api.post(`/schedule-runs/${runId}/publish`);
  return res.data;
}