import { api } from "./clients";

export async function getCurrentUser() {
  const response = await api.get("/me");
  return response.data;
}