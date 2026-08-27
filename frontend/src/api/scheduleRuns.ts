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