import { api } from "./clients";

// A row in the student editor's IEP Services list. `id` is set for
// services already saved; rows without one are created on save.
export interface IepService {
  id?: string;
  service_type: string;
  sessions_per_week: number | null;
  minutes_per_session: number | null;
  notes?: string | null;
}

// The server stores minutes per WEEK; the editor asks for minutes per
// session, as IEPs state them ("30 min, 2x/week").
export function toIepServiceRow(svc: any): IepService {
  if (svc.minutes_per_session !== undefined) return svc;
  const weekly = svc.minutes_per_week ?? svc.minutes ?? null;
  const sessions = svc.sessions_per_week ?? null;
  return {
    id: svc.id,
    service_type: svc.service_type,
    sessions_per_week: sessions,
    minutes_per_session:
      weekly == null ? null : sessions ? Math.round(weekly / sessions) : weekly,
    notes: svc.notes ?? null,
  };
}

function toPayload(row: IepService) {
  const sessions = row.sessions_per_week ?? 1;
  return {
    service_type: row.service_type,
    sessions_per_week: sessions,
    minutes_per_week: sessions * (row.minutes_per_session ?? 0),
  };
}

// Saves the edited list against what was loaded: new rows are created,
// changed rows updated, missing rows deleted. Unchanged rows aren't
// touched, so their minutes aren't rewritten by rounding.
export async function syncStudentServices(studentId: string, original: any[], edited: any[]) {
  const before = new Map(original.map(toIepServiceRow).filter((s) => s.id).map((s) => [s.id!, s]));
  const after = edited.map(toIepServiceRow);
  const keptIds = new Set(after.map((s) => s.id).filter(Boolean));

  for (const row of after) {
    const old = row.id ? before.get(row.id) : undefined;
    if (!old) {
      await api.post(`/students/${studentId}/services`, toPayload(row));
    } else if (
      old.service_type !== row.service_type ||
      old.sessions_per_week !== row.sessions_per_week ||
      old.minutes_per_session !== row.minutes_per_session
    ) {
      await api.put(`/students/${studentId}/services/${row.id}`, toPayload(row));
    }
  }
  for (const id of before.keys()) {
    if (!keptIds.has(id)) await api.delete(`/students/${studentId}/services/${id}`);
  }
}
