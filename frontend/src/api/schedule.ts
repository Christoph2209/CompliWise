import { api } from "./clients";

export async function getSchedule() {
  const response = await api.get("/schedule");
  return response.data;
}

import axios from "axios";

export async function updateScheduleEntry(id: string, payload: any) {
  const res = await axios.put(
    `http://localhost:8000/schedule/${id}`,
    payload
  );
  return res.data;
}