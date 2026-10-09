import { api } from "./clients";
import type { Role } from "../context/authTypes";

export type PasswordRequestStatus = "pending" | "approved" | "rejected" | "cancelled";

export type PasswordChangeRequest = {
  id: string;
  status: PasswordRequestStatus;
  requested_at: string | null;
  reviewed_at: string | null;
  review_note: string | null;
  reviewed_by?: string;
  user?: {
    id: string;
    email: string;
    full_name: string | null;
    role: Role;
  };
};

export type MyPasswordRequestInfo = {
  requires_approval: boolean;
  request: PasswordChangeRequest | null;
};

export const MIN_PASSWORD_LENGTH = 10;

export async function getMyPasswordRequest(): Promise<MyPasswordRequestInfo> {
  const { data } = await api.get<MyPasswordRequestInfo>("/me/password-change-request");
  return data;
}

/** Admins: changes immediately ("changed"). Everyone else: files a request ("pending"). */
export async function changeMyPassword(currentPassword: string, newPassword: string) {
  const { data } = await api.post<{ status: "changed" | "pending"; request?: PasswordChangeRequest }>(
    "/me/password",
    { current_password: currentPassword, new_password: newPassword }
  );
  return data;
}

export async function cancelMyPasswordRequest() {
  await api.delete("/me/password-change-request");
}

export async function listPasswordRequests(status: "pending" | "all" = "pending") {
  const { data } = await api.get<PasswordChangeRequest[]>("/admin/password-change-requests", {
    params: { status },
  });
  return data;
}

export async function approvePasswordRequest(id: string, note?: string) {
  const { data } = await api.post<PasswordChangeRequest>(
    `/admin/password-change-requests/${id}/approve`,
    { note: note || null }
  );
  return data;
}

export async function rejectPasswordRequest(id: string, note?: string) {
  const { data } = await api.post<PasswordChangeRequest>(
    `/admin/password-change-requests/${id}/reject`,
    { note: note || null }
  );
  return data;
}
