import { useState } from "react";
import { Link } from "react-router-dom";
import {
  commitImport,
  previewImport,
  type ImportFileReport,
  type ImportPreview,
  type ImportResult,
} from "../api/import";
import "../components/Dashboard.css";

const FILE_LABEL: Record<ImportFileReport["file"], string> = {
  students: "Students",
  staff: "Staff",
};

/** The server's error text, whether `detail` is a string or the
 * {message, files} object /import/commit sends when it refuses a file. */
function errorText(err: any, fallback: string): string {
  const detail = err?.response?.data?.detail;
  if (typeof detail === "string") return detail;
  if (typeof detail?.message === "string") return detail.message;
  return fallback;
}

function FileReport({ report }: { report: ImportFileReport }) {
  return (
    <section className="panel" style={{ height: "auto", marginBottom: 16 }}>
      <h2>{FILE_LABEL[report.file]} file</h2>
      <p style={{ margin: "0 0 10px", fontSize: 14 }}>
        {report.rows_read} row{report.rows_read === 1 ? "" : "s"} read ·{" "}
        <strong>{report.new_records} new</strong> · {report.updated_records} already on file
        (will be updated)
        {report.services_found != null && ` · ${report.services_found} IEP service(s) found`}
      </p>

      {report.issues.length === 0 ? (
        <p className="empty">No problems found.</p>
      ) : (
        <>
          <p style={{ margin: "0 0 8px", fontSize: 14 }}>
            {report.errors} error{report.errors === 1 ? "" : "s"}, {report.warnings} warning
            {report.warnings === 1 ? "" : "s"}
          </p>
          <div style={{ maxHeight: 320, overflow: "auto" }}>
            <table className="dashboard-table" style={{ width: "100%", fontSize: 13 }}>
              <thead>
                <tr>
                  <th align="left">Row</th>
                  <th align="left">Type</th>
                  <th align="left">Column</th>
                  <th align="left">Problem</th>
                </tr>
              </thead>
              <tbody>
                {report.issues.map((issue, i) => (
                  <tr key={i}>
                    <td>{issue.row ?? "File"}</td>
                    <td
                      style={{
                        color: issue.severity === "error" ? "var(--red-500)" : "var(--text)",
                        fontWeight: issue.severity === "error" ? 700 : 400,
                      }}
                    >
                      {issue.severity === "error" ? "Error" : "Warning"}
                    </td>
                    <td>{issue.field ?? "—"}</td>
                    <td>{issue.message}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </section>
  );
}

export default function ImportData() {
  const [studentsFile, setStudentsFile] = useState<File | null>(null);
  const [staffFile, setStaffFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<ImportPreview | null>(null);
  const [result, setResult] = useState<ImportResult | null>(null);
  const [busy, setBusy] = useState<"checking" | "importing" | null>(null);
  const [error, setError] = useState<string | null>(null);
  // Bumped after an import so the file inputs remount empty.
  const [formKey, setFormKey] = useState(0);

  const files = { students: studentsFile, staff: staffFile };
  const hasFile = Boolean(studentsFile || staffFile);

  // A check only covers the files that were picked when it ran.
  function pickFile(set: (file: File | null) => void, file: File | null) {
    set(file);
    setPreview(null);
    setResult(null);
    setError(null);
  }

  async function check() {
    setBusy("checking");
    setError(null);
    setResult(null);
    try {
      setPreview(await previewImport(files));
    } catch (err) {
      setPreview(null);
      setError(errorText(err, "Couldn't check the file. Try again."));
    } finally {
      setBusy(null);
    }
  }

  async function runImport() {
    setBusy("importing");
    setError(null);
    try {
      setResult(await commitImport(files));
      setPreview(null);
      setStudentsFile(null);
      setStaffFile(null);
      setFormKey((k) => k + 1);
    } catch (err: any) {
      // The server re-checks on import; show its report if it refused.
      const refused = err?.response?.data?.detail?.files;
      if (Array.isArray(refused)) setPreview({ can_import: false, files: refused });
      setError(errorText(err, "Import failed. Nothing was saved."));
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="dashboard">
      <div className="dashboard-header">
        <h1>Import Students</h1>
      </div>

      <section className="panel" style={{ height: "auto", marginBottom: 16, maxWidth: 720 }}>
        <h2>Choose a file</h2>
        <p style={{ margin: "0 0 14px", fontSize: 14, color: "var(--text)" }}>
          Upload a CSV or Excel (.xlsx) file to add more students. Students already on file (matched by student ID) are
          updated, not duplicated, and nobody is removed. The file is checked first; nothing is
          saved until you choose Import.
        </p>

        <div key={formKey} style={{ display: "grid", gap: 14, marginBottom: 16 }}>
          <label style={{ display: "grid", gap: 6, fontSize: 14, fontWeight: 600 }}>
            Students file (CSV or Excel)
            <input
              type="file"
              accept=".csv,.xlsx"
              disabled={busy !== null}
              onChange={(e) => pickFile(setStudentsFile, e.target.files?.[0] ?? null)}
            />
          </label>
          <label style={{ display: "grid", gap: 6, fontSize: 14, fontWeight: 600 }}>
            Staff file (CSV or Excel, optional)
            <input
              type="file"
              accept=".csv,.xlsx"
              disabled={busy !== null}
              onChange={(e) => pickFile(setStaffFile, e.target.files?.[0] ?? null)}
            />
          </label>
        </div>

        <div style={{ display: "flex", gap: 10 }}>
          <button
            className="action-btn"
            style={{ width: "auto", padding: "11px 20px", marginBottom: 0 }}
            disabled={!hasFile || busy !== null}
            onClick={check}
          >
            {busy === "checking" ? "Checking…" : "Check file"}
          </button>
          <button
            className="action-btn"
            style={{ width: "auto", padding: "11px 20px", marginBottom: 0 }}
            disabled={!preview?.can_import || busy !== null}
            onClick={runImport}
          >
            {busy === "importing" ? "Importing…" : "Import"}
          </button>
        </div>

        {preview && !preview.can_import && (
          <p style={{ margin: "14px 0 0", fontSize: 14, color: "var(--red-500)" }}>
            Fix the errors below and upload the file again. A file with errors is not imported at
            all.
          </p>
        )}
        {error && (
          <p role="alert" style={{ margin: "14px 0 0", fontSize: 14, color: "var(--red-500)" }}>
            {error}
          </p>
        )}
      </section>

      {result && (
        <section className="panel" style={{ height: "auto", marginBottom: 16, maxWidth: 720 }}>
          <h2>Import complete</h2>
          <p style={{ margin: 0, fontSize: 14 }}>
            {result.students_imported} student{result.students_imported === 1 ? "" : "s"} and{" "}
            {result.staff_imported} staff record{result.staff_imported === 1 ? "" : "s"} imported
            or updated, with {result.services_imported} new IEP service
            {result.services_imported === 1 ? "" : "s"}
            {result.warnings > 0 && ` (${result.warnings} warning${result.warnings === 1 ? "" : "s"})`}.
            New students appear in schedules the next time you generate one.{" "}
            <Link to="/students">View students</Link>
          </p>
        </section>
      )}

      {preview?.files.map((report) => (
        <FileReport key={report.file} report={report} />
      ))}
    </div>
  );
}
