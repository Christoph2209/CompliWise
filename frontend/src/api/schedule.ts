import type { ScheduleConfigDefaults, ScheduleGenerationConfig } from "../components/GenerateScheduleModal";
import { api } from "./clients";

export async function getSchedule(runId?: string) {
  const res = await api.get("/schedule", {
    params: runId ? { run_id: runId } : {},
  });
  return res.data;
}

// One row per teacher per class/session (GET /staff-schedule). Unlike
// /schedule, which is one row per student, this includes prep and lunch.
export interface StaffScheduleEntry {
  id: string;
  run_id: string;
  staff_id: string | null;
  staff_name: string | null;
  day_of_week: string;
  period: number; // == start_minute
  period_label?: string | null;
  subject: string;
  grade?: string | null;
  service_type?: string | null;
  is_pullout: boolean;
  is_flex_period: boolean;
  student_count: number;
  start_minute: number;
  end_minute: number;
  time_range?: string | null;
  delivery?: "pullout" | "push_in" | "class" | "prep" | "break" | null;
  block_subject?: string | null;
  room?: string | null;
}

// Omitting runId returns the latest full schedule run. Teachers only
// ever get their own rows back, whatever staffId says.
export async function getStaffSchedule(runId?: string, staffId?: string) {
  const params: Record<string, string> = {};
  if (runId) params.run_id = runId;
  if (staffId) params.staff_id = staffId;
  const res = await api.get<StaffScheduleEntry[]>("/staff-schedule", { params });
  return res.data;
}

export async function getMySchedule() {
  const { data } = await api.get("/my-schedule");
  return data;
}

export async function resetSchedule() {
  const { data } = await api.post("/reset-generated-schedules");
  return data;
}

export async function updateScheduleEntry(entryId: string, payload: any) {
  const res = await api.put(`/schedule/${entryId}`, payload);
  return res.data;
}

export interface ScheduleJobStatus {
  status: "queued" | "running" | "complete" | "error";
  current_stage: number;
  stage_name: string | null;
  percent: number;
  message?: string | null;
  result?: any;
  error?: string | null;
}

export async function startScheduleGeneration(config: ScheduleGenerationConfig) {
  const { data } = await api.post("/schedule/generate/start", config);
  return data as { job_id: string };
}

export async function getScheduleGenerationStatus(jobId: string) {
  const { data } = await api.get(`/schedule/generate/status/${jobId}`);
  return data as ScheduleJobStatus;
}

export async function getScheduleConfigDefaults(): Promise<ScheduleConfigDefaults> {
  const { data } = await api.get<ScheduleConfigDefaults>("/schedule/config-defaults");
  return data;
}
