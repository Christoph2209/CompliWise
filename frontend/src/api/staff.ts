import { api } from "./clients";

export interface StaffCreatePayload {
  school_id: string;
  first_name: string;
  last_name: string;
  external_staff_id?: string;
  title?: string;
  grade?: string;
  homeroom?: string;
  room?: string;
  is_certified_sped: boolean;
  is_certified_enl: boolean;
  is_certified_slp: boolean;
  can_deliver_setss: boolean;
  max_students_per_group: number;
}

export async function getStaff() {
  const response = await api.get("/staff");
  return response.data.staff;
}

export async function createStaff(payload: StaffCreatePayload) {
  const response = await api.post("/staff", payload);
  return response.data.staff;
}

export async function updateStaff(id: string | number, updates: {
  grade: string;
  is_certified_sped: boolean;
  is_certified_enl: boolean;
  is_certified_slp: boolean;
  can_deliver_setss: boolean;
  homeroom: string;
}) {
  const response = await api.put(`/staff/${id}`, updates);
  return response.data;
}