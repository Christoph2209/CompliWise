import { api } from "./clients"; // adjust path/filename to match your actual clients.ts
import type { Role } from "../context/authTypes";

export type UnassignedStaff = {
  id: string;
  first_name: string;
  last_name: string;
};

export async function getUnassignedStaff(): Promise<UnassignedStaff[]> {
  const { data } = await api.get<UnassignedStaff[]>("/admin/staff/unassigned");
  return data;
}

export async function addUser(payload: {
  email: string;
  password: string;
  role: Role;
  staff_id?: string;
}) {
  const { data } = await api.post("/admin/users", payload);
  return data;
}