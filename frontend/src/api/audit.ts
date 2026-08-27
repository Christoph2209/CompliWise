import {api} from "./clients";

export interface AuditLogEntry {
  id: string;
  action: string;
  entity_type: string | null;
  entity_id: string | null;
  user_id: string | null;
  user_email: string | null;
  user_name: string | null;
  before_json: Record<string, any> | null;
  after_json: Record<string, any> | null;
  ip_address: string | null;
  created_at: string;
}

export async function getAuditLogs(): Promise<AuditLogEntry[]> {
  const res = await api.get("/audit-logs");
  return res.data;
}