import { api } from "./clients";

export async function getComplianceFlags() {
  const response = await api.get("/compliance-flags");
  return response.data;
}