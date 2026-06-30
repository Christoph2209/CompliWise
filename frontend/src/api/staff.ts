import { api } from "./clients";

export async function getStaff() {
  const response = await api.get("/staff");
  return response.data.staff;
}