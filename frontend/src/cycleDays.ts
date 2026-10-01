// The school runs on a rotating five-day cycle (A-E) rather than the
// calendar week. Mirrors DAYS in backend/scheduling_core.py -- these
// are the values stored in every entry's day_of_week.

export const CYCLE_DAYS = ["A", "B", "C", "D", "E"] as const;
export type CycleDay = (typeof CYCLE_DAYS)[number];

/** "A" -> "A Day" */
export function dayLabel(day: string): string {
  return `${day} Day`;
}
