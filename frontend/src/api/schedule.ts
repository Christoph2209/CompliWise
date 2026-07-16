import { api } from "./clients";

export async function getSchedule() {
  const { data } = await api.get("/schedule");
  return data;
}

export async function getMySchedule() {
  const { data } = await api.get("/my-schedule");
  return data;
}

export async function generateSchedule() {
  const { data } = await api.post("/save-schedule");
  return data;
}

export async function resetSchedule() {
  const { data } = await api.post("/reset-generated-schedules");
  return data;
}

export async function updateScheduleEntry(id: string, payload: any) {
  const { data } = await api.put(`/schedule/${id}`, payload);
  return data;
}