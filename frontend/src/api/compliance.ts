import { api } from "./clients";

export async function getComplianceFlags() {
  const response = await api.get("/compliance-flags");
  return response.data;
}

export async function runComplianceCheck() {
  const response = await api.post("/run-compliance-check");
  return response.data;
}