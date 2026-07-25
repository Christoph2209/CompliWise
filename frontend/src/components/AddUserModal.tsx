import { useEffect, useState } from "react";
import axios from "axios";
import { getUnassignedStaff, addUser, type UnassignedStaff } from "../api/admin";
import type { Role } from "../context/authTypes";

const ROLES: Role[] = ["admin", "principal", "teacher", "aide"];

export default function AddUserModal({
  onClose,
  onCreated,
}: {
  schoolId: string;
  onClose: () => void;
  onCreated: () => void;
}) {
  const [staffOptions, setStaffOptions] = useState<UnassignedStaff[]>([]);
  const [staffId, setStaffId] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState<Role>("teacher");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    getUnassignedStaff()
      .then(setStaffOptions)
      .catch(() => setError("Couldn't load staff list"));
  }, []);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      await addUser({ email, password, role, staff_id: staffId || undefined });
      onCreated();
      onClose();
    } catch (err) {
      if (axios.isAxiosError(err)) {
        setError(err.response?.data?.detail || "Failed to add user");
      } else {
        setError("Something went wrong");
      }
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-card" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <h2 style={{ color: "#0c0c0c" }}>Add User</h2>
          <button className="modal-close" onClick={onClose}>✕</button>
        </div>

        <form onSubmit={handleSubmit} className="modal-form">
          {error && <p className="modal-error">{error}</p>}

          <div className="form-row">
            <label>
              Link to staff member (optional)
              <select value={staffId} onChange={(e) => setStaffId(e.target.value)}>
                <option value="">— No staff record —</option>
                {staffOptions.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.first_name} {s.last_name}
                  </option>
                ))}
              </select>
            </label>
          </div>

          <div className="form-row">
            <label>
              Email
              <input
                type="email"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
              />
            </label>
            <label>
              Role
              <select value={role} onChange={(e) => setRole(e.target.value as Role)}>
                {ROLES.map((r) => (
                  <option key={r} value={r}>{r}</option>
                ))}
              </select>
            </label>
          </div>

          <div className="form-row">
            <label>
              Temporary password
              <input
                type="password"
                required
                minLength={8}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
              />
            </label>
          </div>

          <div className="modal-actions">
            <button type="button" className="secondary" onClick={onClose}>
              Cancel
            </button>
            <button type="submit" disabled={submitting}>
              {submitting ? "Adding..." : "Add User"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}