import { api } from "./clients";

export type ImportIssue = {
  /** Spreadsheet row (header = row 1); null means the whole file. */
  row: number | null;
  severity: "error" | "warning";
  field: string | null;
  message: string;
};

export type ImportFileReport = {
  file: "students" | "staff";
  rows_read: number;
  new_records: number;
  updated_records: number;
  errors: number;
  warnings: number;
  issues: ImportIssue[];
  services_found?: number;
};

export type ImportPreview = {
  can_import: boolean;
  files: ImportFileReport[];
};

export type ImportResult = {
  students_imported: number;
  staff_imported: number;
  services_imported: number;
  services_already_present?: number;
  warnings: number;
};

export type ImportFiles = {
  students?: File | null;
  staff?: File | null;
};

function toForm(files: ImportFiles): FormData {
  const form = new FormData();
  if (files.students) form.append("students_file", files.students);
  if (files.staff) form.append("staff_file", files.staff);
  return form;
}

/** Checks the files row by row. Saves nothing. */
export async function previewImport(files: ImportFiles): Promise<ImportPreview> {
  const { data } = await api.post<ImportPreview>("/import/preview", toForm(files), {
    headers: { "Content-Type": "multipart/form-data" },
  });
  return data;
}

/** Imports the files. The server re-checks them and refuses (422) on any error. */
export async function commitImport(files: ImportFiles): Promise<ImportResult> {
  const { data } = await api.post<ImportResult>("/import/commit", toForm(files), {
    headers: { "Content-Type": "multipart/form-data" },
  });
  return data;
}
