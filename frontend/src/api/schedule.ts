import { api } from "./clients";
import axios from "axios";

export async function getSchedule() {
  const response = await api.get("/schedule");
  return response.data;
}

export async function generateSchedule() {
  const res = await fetch("http://localhost:8000/save-schedule", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
  });

  if (!res.ok) throw new Error("Failed to generate schedule");

  return res.json();
}

export async function resetSchedule() {
  const res = await fetch("http://localhost:8000/reset-generated-schedules", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
  });

  if (!res.ok) throw new Error("Failed to erase schedule");
  return res.json();
}

export async function updateScheduleEntry(id: string, payload: any) {
  const res = await axios.put(
    `http://localhost:8000/schedule/${id}`,
    payload
  );
  return res.data;
}