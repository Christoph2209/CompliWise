import { getStudents } from "./students";
import { getStaff } from "./staff";
import { getSchedule } from "./schedule";
import { getComplianceFlags } from "./compliance";

const STALE_MS = 60_000; // treat cached data as fresh for 60s

type DashboardData = {
  students: any[];
  staff: any[];
  schedule: any[];
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
    const [students, staff, schedule, flags] = await Promise.all([
      getStudents(),
      getStaff(),
      getSchedule(),
      getComplianceFlags(),
    ]);
    const data: DashboardData = {
      students: students || [],
      staff: staff || [],
      schedule: schedule || [],
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