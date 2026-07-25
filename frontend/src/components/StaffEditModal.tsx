import { useState } from "react";
import { createPortal } from "react-dom";
import { updateStaff } from "../api/staff";
import "./StaffEditor.css";

interface StaffMember {
  id: string | number;
  first_name: string;
  last_name: string;
  title: string;
  grade: string;
  is_certified_sped: boolean;
  is_certified_enl: boolean;
  is_certified_slp: boolean;
  can_deliver_setss: boolean;
  homeroom: string;
}

interface StaffEditModalProps {
  staff: StaffMember;
  onClose: () => void;
  onSaved: (updated: StaffMember) => void;
}

const GRADE_OPTIONS = [ "K", "1", "2", "3", "4", "5"];

export default function StaffEditModal({ staff, onClose, onSaved }: StaffEditModalProps) {
  const [form, setForm] = useState({
    grade: staff.grade,
    is_certified_sped: staff.is_certified_sped,
    is_certified_enl: staff.is_certified_enl,
    is_certified_slp: staff.is_certified_slp,
    can_deliver_setss: staff.can_deliver_setss,
    homeroom: staff.homeroom,
  });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const toggle = (field: keyof typeof form) => {
    setForm((prev) => ({ ...prev, [field]: !prev[field] }));
  };

  const handleSave = async () => {
    setSaving(true);
    setError(null);
    try {
      const updated = await updateStaff(staff.id, form);
      onSaved(updated);
      onClose();
    } catch (err) {
      setError("Failed to save changes. Please try again.");
    } finally {
      setSaving(false);
    }
  };

  return createPortal(
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-content" onClick={(e) => e.stopPropagation()}>
        <h2>
          {staff.first_name} {staff.last_name}
        </h2>
        <p className="staff-title-sub">{staff.title}</p>

        <div className="form-group">
          <label>Grade</label>
          <select
            value={form.grade}
            onChange={(e) => setForm((prev) => ({ ...prev, grade: e.target.value }))}
          >
            {GRADE_OPTIONS.map((g) => (
              <option key={g} value={g}>
                {g}
              </option>
            ))}
          </select>
        </div>
        <div className="form-group">
          <label>Homeroom</label>
          <input
            type="text"
            value={form.homeroom}
            onChange={(e) => setForm((prev) => ({ ...prev, homeroom: e.target.value }))}
          />
        </div>
        <div className="form-group">
          <label>Certifications & Services</label>
          <div className="checkbox-row">
            <label>
              <input
                type="checkbox"
                checked={form.is_certified_sped}
                onChange={() => toggle("is_certified_sped")}
              />
              SpEd Certified
            </label>
            <label>
              <input
                type="checkbox"
                checked={form.is_certified_enl}
                onChange={() => toggle("is_certified_enl")}
              />
              ENL Certified
            </label>
            <label>
              <input
                type="checkbox"
                checked={form.is_certified_slp}
                onChange={() => toggle("is_certified_slp")}
              />
              SLP Certified
            </label>
            <label>
              <input
                type="checkbox"
                checked={form.can_deliver_setss}
                onChange={() => toggle("can_deliver_setss")}
              />
              Can Deliver SETSS
            </label>
          </div>
        </div>

        {error && <p className="form-error">{error}</p>}

        <div className="modal-actions">
          <button onClick={onClose} disabled={saving}>
            Cancel
          </button>
          <button onClick={handleSave} disabled={saving} className="primary">
            {saving ? "Saving..." : "Save Changes"}
          </button>
        </div>
      </div>
    </div>,
    document.body
  );
}