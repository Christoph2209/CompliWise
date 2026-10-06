import { getStudents } from "./students";
import { getStaff } from "./staff";
import { getScheduleRuns } from "./scheduleRuns";
import { getComplianceFlags } from "./compliance";

const STALE_MS = 60_000; // treat cached data as fresh for 60s

type DashboardData = {
  students: any[];
  staff: any[];
  // Generated schedules not yet published (from the run list).
  draftScheduleCount: number;
  // When the current published schedule was published, if any.
  lastPublishedAt: string | null;
  flags: any[];
  fetchedAt: number;
};

let cache: DashboardData | null = null;
let inFlight: Promise<DashboardData> | null = null;

export async function loadDashboard(force = false): Promise<DashboardData> {
  const isStale = !cache || Date.now() - cache.fetchedAt > STALE_MS;

  if (!force && cache && !isStale) {
    return cache; // serve instantly, no request
  }

  if (inFlight) return inFlight; // dedupe concurrent calls

  inFlight = (async () => {
    const [students, staff, runs, flags] = await Promise.all([
      getStudents(),
      getStaff(),
      getScheduleRuns(),
      getComplianceFlags(),
    ]);
    const data: DashboardData = {
      students: students || [],
      staff: staff || [],
      draftScheduleCount: (runs || []).filter((r) => r.status !== "published").length,
      lastPublishedAt:
        (runs || [])
          .map((r) => r.published_at)
          .filter((d): d is string => !!d)
          .sort()
          .at(-1) ?? null,
      flags: flags || [],
      fetchedAt: Date.now(),
    };
    cache = data;
    inFlight = null;
    return data;
  })();

  return inFlight;
}

export function invalidateDashboard() {
  cache = null;
}