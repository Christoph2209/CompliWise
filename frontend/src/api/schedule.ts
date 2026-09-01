import type { ScheduleGenerationConfig } from "../components/GenerateScheduleModal";
import { api } from "./clients";

export async function getSchedule(runId?: string) {
  const res = await api.get("/schedule", {
    params: runId ? { run_id: runId } : {},
  });
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