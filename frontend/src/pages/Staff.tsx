import { useEffect, useState } from "react";
import { getStaff } from "../api/staff";
import StaffEditModal from "../components/StaffEditModal";
import "../components/StaffEditor.css";

export default function Staff() {
  const [staff, setStaff] = useState<any[]>([]);
  const [search, setSearch] = useState("");
  const [selectedStaff, setSelectedStaff] = useState<any | null>(null);

  useEffect(() => {
    getStaff().then(setStaff);
  }, []);

  const filteredStaff = staff.filter((member) => {
    const name = `${member.first_name} ${member.last_name}`.toLowerCase();
    return name.includes(search.toLowerCase());
  });

  const handleSaved = (updated: any) => {
    setStaff((prev) => prev.map((m) => (m.id === updated.id ? updated : m)));
  };

  return (
    <div className="staff-page">
      <h1>Staff</h1>

      <input
        className="staff-search"
        placeholder="Search staff..."
        value={search}
        onChange={(e) => setSearch(e.target.value)}
      />

      <div className="staff-grid">
        {filteredStaff.map((member) => (
          <div
            key={member.id}
            className="staff-card"
            onClick={() => setSelectedStaff(member)}
            style={{ cursor: "pointer" }}
          >
            <div className="staff-header">
              <div className="staff-name">
                {member.first_name} {member.last_name}
              </div>
              <div className="staff-title">{member.title}</div>
            </div>

            <div className="staff-badges">
              <span className={`badge ${member.is_certified_sped ? "yes" : "no"}`}>SpEd</span>
              <span className={`badge ${member.is_certified_enl ? "yes" : "no"}`}>ENL</span>
              <span className={`badge ${member.is_certified_slp ? "yes" : "no"}`}>SLP</span>
              <span className={`badge ${member.can_deliver_setss ? "yes" : "no"}`}>SETSS</span>
            </div>

            <div className="staff-footer">
              <div>
                <strong>Grade:</strong> {member.grade}
              </div>
            </div>
          </div>
        ))}
      </div>

      {selectedStaff && (
        <StaffEditModal
          staff={selectedStaff}
          onClose={() => setSelectedStaff(null)}
          onSaved={handleSaved}
        />
      )}
    </div>
  );
}