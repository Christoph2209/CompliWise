import { useEffect, useState } from "react";
import type { FormEvent } from "react";
// Adjust this import to match wherever your shared axios instance lives
// (memory says clients.ts exports `api` with baseURL from VITE_API_URL
// and withCredentials: true -- use that same instance here, not fetch).
import {api} from "../api/clients";

import "../components/SetupWizard.css";

type SetupStatus = {
  database_connectable: boolean;
  setup_complete: boolean;
};

type WizardStep = "checking" | "db-unreachable" | "admin" | "csv" | "done";

type LedgerState = "pending" | "active" | "done";

interface SetupWizardProps {
  /** Called once setup is confirmed complete (existing or freshly finished). Wire this to redirect to /login. */
  onComplete: () => void;
}

function StatusLedger({ step }: { step: WizardStep }) {
  const dbState: LedgerState =
    step === "checking" || step === "db-unreachable" ? "active" : "done";
  const adminState: LedgerState =
    step === "admin" ? "active" : step === "csv" || step === "done" ? "done" : "pending";
  const dataState: LedgerState =
    step === "csv" ? "active" : step === "done" ? "done" : "pending";

  const rows: { label: string; state: LedgerState }[] = [
    { label: "Database", state: dbState },
    { label: "Admin account", state: adminState },
    { label: "Starter data", state: dataState },
  ];

  return (
    <ul className="setup-ledger" aria-label="Setup progress">
      {rows.map((row) => (
        <li key={row.label} className={`setup-ledger__row setup-ledger__row--${row.state}`}>
          <span className="setup-ledger__mark" aria-hidden="true">
            {row.state === "done" ? "✓" : row.state === "active" ? "…" : "·"}
          </span>
          <span className="setup-ledger__label">{row.label}</span>
        </li>
      ))}
    </ul>
  );
}

export default function SetupWizard({ onComplete }: SetupWizardProps) {
  const [step, setStep] = useState<WizardStep>("checking");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  // Admin/school form fields
  const [schoolName, setSchoolName] = useState("");
  const [districtName, setDistrictName] = useState("");
  const [adminFullName, setAdminFullName] = useState("");
  const [adminEmail, setAdminEmail] = useState("");
  const [adminPassword, setAdminPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");

  // CSV step fields
  const [studentsFile, setStudentsFile] = useState<File | null>(null);
  const [staffFile, setStaffFile] = useState<File | null>(null);
  const [importSummary, setImportSummary] = useState<{ students_imported: number; staff_imported: number } | null>(null);

  // No setState here -- just fetches and returns/throws. Both the mount
  // effect and checkStatus() below build on this, but only they touch
  // state, and only after an await.
  const fetchSetupStatus = async (): Promise<SetupStatus> => {
    const { data } = await api.get<SetupStatus>("/setup/status");
    return data;
  };

  // Reusable version for the Retry button and the polling interval.
  // Neither of those call sites is an effect body, so setState here is
  // unremarkable -- it's only a problem when called synchronously from
  // inside a useEffect callback (see the mount effect below).
  const checkStatus = async () => {
    setError(null);
    try {
      const data = await fetchSetupStatus();
      if (data.setup_complete) {
        onComplete();
        return;
      }
      setStep(data.database_connectable ? "admin" : "db-unreachable");
    } catch {
      setStep("db-unreachable");
    }
  };

  // Initial check on mount. Deliberately doesn't call the checkStatus()
  // helper above -- that calls setError(null) synchronously before its
  // first await, which react-hooks/set-state-in-effect flags when
  // called directly from an effect body. This inline version only sets
  // state in the continuation after the await, which the rule wants.
  useEffect(() => {
    let ignore = false;

    (async () => {
      try {
        const data = await fetchSetupStatus();
        if (ignore) return;
        if (data.setup_complete) {
          onComplete();
          return;
        }
        setStep(data.database_connectable ? "admin" : "db-unreachable");
      } catch {
        if (!ignore) setStep("db-unreachable");
      }
    })();

    return () => {
      ignore = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // While the DB is unreachable (e.g. the Postgres container is still
  // starting), keep checking in the background instead of making the
  // person keep clicking Retry. The effect body itself only calls
  // setInterval -- checkStatus runs later, on the timer's own callback,
  // not synchronously inside this effect -- so it isn't flagged either.
  useEffect(() => {
    if (step !== "db-unreachable") return;
    const interval = setInterval(checkStatus, 4000);
    return () => clearInterval(interval);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [step]);

  const handleAdminSubmit = async (event: FormEvent) => {
    event.preventDefault();
    setError(null);

    if (adminPassword !== confirmPassword) {
      setError("Passwords don't match.");
      return;
    }
    if (adminPassword.length < 8) {
      setError("Password should be at least 8 characters.");
      return;
    }

    setSubmitting(true);
    try {
      await api.post("/setup/initialize", {
        school_name: schoolName.trim(),
        district_name: districtName.trim() || null,
        admin_email: adminEmail.trim(),
        admin_password: adminPassword,
        admin_full_name: adminFullName.trim() || null,
      });
      setStep("csv");
    } catch (err: any) {
      setError(err?.response?.data?.detail ?? "Couldn't create the admin account. Check the details and try again.");
    } finally {
      setSubmitting(false);
    }
  };

  const handleCsvSubmit = async (event: FormEvent) => {
    event.preventDefault();
    setError(null);

    if (!studentsFile && !staffFile) {
      setStep("done");
      return;
    }

    setSubmitting(true);
    try {
      const form = new FormData();
      if (studentsFile) form.append("students_file", studentsFile);
      if (staffFile) form.append("staff_file", staffFile);

      const { data } = await api.post("/setup/import-csv", form, {
        headers: { "Content-Type": "multipart/form-data" },
      });
      setImportSummary(data);
      setStep("done");
    } catch (err: any) {
      setError(err?.response?.data?.detail ?? "Import failed. You can skip this and import the CSVs later.");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="setup-wizard">
      <div className="setup-wizard__panel">
        <div className="setup-wizard__ledger-col">
          <div className="setup-wizard__brand">CompliWise</div>
          <p className="setup-wizard__brand-sub">First-run setup</p>
          <StatusLedger step={step} />
        </div>

        <div className="setup-wizard__content-col">
          {step === "checking" && (
            <div className="setup-wizard__state">
              <p>Checking database connection…</p>
            </div>
          )}

          {step === "db-unreachable" && (
            <div className="setup-wizard__state">
              <h1>Waiting for the database</h1>
              <p>
                CompliWise can't reach Postgres yet. If this server just started, the database
                container may still be coming up — this page will keep checking automatically.
              </p>
              <button type="button" className="setup-wizard__btn" onClick={checkStatus}>
                Check again
              </button>
            </div>
          )}

          {step === "admin" && (
            <form className="setup-wizard__state" onSubmit={handleAdminSubmit}>
              <h1>Set up this school</h1>
              <p>This creates your school record and the first admin account.</p>

              <label className="setup-wizard__field">
                <span>School name</span>
                <input
                  required
                  value={schoolName}
                  onChange={(e) => setSchoolName(e.target.value)}
                  placeholder="e.g. Lakeview Elementary"
                />
              </label>

              <label className="setup-wizard__field">
                <span>District (optional)</span>
                <input
                  value={districtName}
                  onChange={(e) => setDistrictName(e.target.value)}
                />
              </label>

              <hr className="setup-wizard__divider" />

              <label className="setup-wizard__field">
                <span>Admin full name</span>
                <input
                  value={adminFullName}
                  onChange={(e) => setAdminFullName(e.target.value)}
                />
              </label>

              <label className="setup-wizard__field">
                <span>Admin email</span>
                <input
                  required
                  type="email"
                  value={adminEmail}
                  onChange={(e) => setAdminEmail(e.target.value)}
                />
              </label>

              <label className="setup-wizard__field">
                <span>Password</span>
                <input
                  required
                  type="password"
                  minLength={8}
                  value={adminPassword}
                  onChange={(e) => setAdminPassword(e.target.value)}
                />
              </label>

              <label className="setup-wizard__field">
                <span>Confirm password</span>
                <input
                  required
                  type="password"
                  value={confirmPassword}
                  onChange={(e) => setConfirmPassword(e.target.value)}
                />
              </label>

              {error && <p className="setup-wizard__error">{error}</p>}

              <button type="submit" className="setup-wizard__btn" disabled={submitting}>
                {submitting ? "Creating…" : "Create school & admin account"}
              </button>
            </form>
          )}

          {step === "csv" && (
            <form className="setup-wizard__state" onSubmit={handleCsvSubmit}>
              <h1>Import starter data</h1>
              <p>Optional — you can also do this later from the app.</p>

              <label className="setup-wizard__field">
                <span>Students CSV</span>
                <input
                  type="file"
                  accept=".csv"
                  onChange={(e) => setStudentsFile(e.target.files?.[0] ?? null)}
                />
              </label>

              <label className="setup-wizard__field">
                <span>Staff CSV</span>
                <input
                  type="file"
                  accept=".csv"
                  onChange={(e) => setStaffFile(e.target.files?.[0] ?? null)}
                />
              </label>

              {error && <p className="setup-wizard__error">{error}</p>}

              <div className="setup-wizard__actions">
                <button type="submit" className="setup-wizard__btn" disabled={submitting}>
                  {submitting ? "Importing…" : "Import & continue"}
                </button>
                <button
                  type="button"
                  className="setup-wizard__btn setup-wizard__btn--ghost"
                  disabled={submitting}
                  onClick={() => setStep("done")}
                >
                  Skip for now
                </button>
              </div>
            </form>
          )}

          {step === "done" && (
            <div className="setup-wizard__state">
              <h1>You're set up</h1>
              {importSummary ? (
                <p>
                  Imported {importSummary.students_imported} students and{" "}
                  {importSummary.staff_imported} staff records.
                </p>
              ) : (
                <p>You can import student and staff CSVs any time from the app.</p>
              )}
              <button type="button" className="setup-wizard__btn" onClick={onComplete}>
                Go to login
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}