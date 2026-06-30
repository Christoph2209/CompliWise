import { useEffect, useState } from "react";
import { getStaff } from "../api/staff";
import "../components/StaffEditor.css";

export default function Staff() {
  const [staff, setStaff] = useState<any[]>([]);
  const [search, setSearch] = useState("");

  useEffect(() => {
    getStaff().then(setStaff);
  }, []);

  const filteredStaff = staff.filter((member) => {
    const name = `${member.first_name} ${member.last_name}`.toLowerCase();
    return name.includes(search.toLowerCase());
  });

  return (
    <div className="staff-page">
      <h1>Staff</h1>

      {/* Search */}
      <input
        className="staff-search"
        placeholder="Search staff..."
        value={search}
        onChange={(e) => setSearch(e.target.value)}
      />

      {/* Grid */}
      <div className="staff-grid">
        {filteredStaff.map((member) => (
          <div key={member.id} className="staff-card">

            <div className="staff-header">
              <div className="staff-name">
                {member.first_name} {member.last_name}
              </div>

              <div className="staff-title">
                {member.title}
              </div>
            </div>

            <div className="staff-badges">
              <span className={`badge ${member.is_certified_sped ? "yes" : "no"}`}>
                SpEd
              </span>

              <span className={`badge ${member.is_certified_enl ? "yes" : "no"}`}>
                ENL
              </span>

              <span className={`badge ${member.is_certified_slp ? "yes" : "no"}`}>
                SLP
              </span>

              <span className={`badge ${member.is_certified_setss ? "yes" : "no"}`}>
                SETSS
              </span>
            </div>

            <div className="staff-footer">
              <div>
                <strong>Max Group:</strong> {member.max_students_per_group}
              </div>
            </div>

          </div>
        ))}
      </div>
    </div>
  );
}