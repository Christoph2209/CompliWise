import { useState } from "react";
import { createStaff } from "../api/staff";
import type { StaffCreatePayload } from "../api/staff";
import "./AddStaffModal.css";

interface AddStaffModalProps {
  schoolId: string;
  onClose: () => void;
  onCreated: () => void;
}

const emptyForm: StaffCreatePayload = {
  school_id: "",
  first_name: "",
  last_name: "",
  external_staff_id: "",
  title: "",
  grade: "",
  homeroom: "",
  room: "",
  is_certified_sped: false,
  is_certified_enl: false,
  is_certified_slp: false,
  can_deliver_setss: false,
  max_students_per_group: 6,
};

export default function AddStaffModal({ schoolId, onClose, onCreated }: AddStaffModalProps) {
  const [form, setForm] = useState<StaffCreatePayload>({ ...emptyForm, school_id: schoolId });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function update<K extends keyof StaffCreatePayload>(key: K, value: StaffCreatePayload[K]) {
    setForm((prev) => ({ ...prev, [key]: value }));
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();

    if (!form.first_name.trim() || !form.last_name.trim()) {
      setError("First and last name are required.");
      return;
    }

    setSaving(true);
    setError(null);

    try {
      await createStaff({
        ...form,
        external_staff_id: form.external_staff_id || undefined,
        title: form.title || undefined,
        grade: form.grade || undefined,
        homeroom: form.homeroom || undefined,
        room: form.room || undefined,
      });

      onCreated();
      onClose();
    } catch (err: any) {
      setError(err?.response?.data?.detail || "Failed to create staff member.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-card" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <h2>Add Staff Member</h2>
          <button className="modal-close" onClick={onClose} aria-label="Close">✕</button>
        </div>

        <form onSubmit={handleSubmit} className="modal-form">
          <div className="form-row">
            <label>
              First name *
              <input
                value={form.first_name}
                onChange={(e) => update("first_name", e.target.value)}
                required
              />
            </label>
            <label>
              Last name *
              <input
                value={form.last_name}
                onChange={(e) => update("last_name", e.target.value)}
                required
              />
            </label>
          </div>

          <div className="form-row">
            <label>
              Title
              <input
                value={form.title}
                onChange={(e) => update("title", e.target.value)}
                placeholder="e.g. Special Education Teacher"
              />
            </label>
            <label>
              External staff ID
              <input
                value={form.external_staff_id}
                onChange={(e) => update("external_staff_id", e.target.value)}
              />
            </label>
          </div>

          <div className="form-row">
            <label>
              Grade
              <input
                value={form.grade}
                onChange={(e) => update("grade", e.target.value)}
                placeholder="e.g. 2 or K/1"
              />
            </label>
            <label>
              Homeroom
              <input
                value={form.homeroom}
                onChange={(e) => update("homeroom", e.target.value)}
              />
            </label>
            <label>
              Room
              <input
                value={form.room}
                onChange={(e) => update("room", e.target.value)}
              />
            </label>
          </div>

          <div className="form-row">
            <label>
              Max students per group *
              <input
                type="number"
                min={1}
                value={form.max_students_per_group}
                onChange={(e) => update("max_students_per_group", Number(e.target.value))}
                required
              />
            </label>
          </div>

          <fieldset className="certifications">
            <legend>Certifications</legend>

            <label className="checkbox-label">
              <input
                type="checkbox"
                checked={form.is_certified_sped}
                onChange={(e) => update("is_certified_sped", e.target.checked)}
              />
              SPED certified
            </label>

            <label className="checkbox-label">
              <input
                type="checkbox"
                checked={form.is_certified_enl}
                onChange={(e) => update("is_certified_enl", e.target.checked)}
              />
              ENL certified
            </label>

            <label className="checkbox-label">
              <input
                type="checkbox"
                checked={form.is_certified_slp}
                onChange={(e) => update("is_certified_slp", e.target.checked)}
              />
              SLP certified
            </label>

            <label className="checkbox-label">
              <input
                type="checkbox"
                checked={form.can_deliver_setss}
                onChange={(e) => update("can_deliver_setss", e.target.checked)}
              />
              Can deliver SETSS
            </label>
          </fieldset>

          {error && <p className="modal-error">{error}</p>}

          <div className="modal-actions">
            <button type="button" className="secondary" onClick={onClose} disabled={saving}>
              Cancel
            </button>
            <button type="submit" disabled={saving}>
              {saving ? "Saving..." : "Add Staff Member"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}