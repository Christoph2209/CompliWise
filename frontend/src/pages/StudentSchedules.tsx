import { useEffect, useState } from "react";
import { getSchedule, updateScheduleEntry } from "../api/schedule";
import { getStaff } from "../api/staff";
import { useAuth } from "../context/authContext";

const DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"];
const PERIODS = [1, 2, 3, 4, 5, 6, 7];

interface StaffMember {
  id: string;
  first_name: string;
  last_name: string;
  title?: string;
}

interface ScheduleEntry {
  id: string;
  student_id: string;
  student_name: string;
  grade: string;
  day_of_week: string;
  period: number;
  subject: string;
  staff_id?: string;
  staff_name?: string;
  service_type?: string;
  is_pullout: boolean;
  is_flex_period?: boolean;
}

export default function StudentSchedules() {
  const { user } = useAuth();
  const isTeacher = user?.role === "teacher";
  const myStaffId = user?.staff_member?.id;

  const [entries, setEntries] = useState<ScheduleEntry[]>([]);
  const [selectedStudent, setSelectedStudent] = useState<string | null>(null);
  const [editingCell, setEditingCell] = useState<ScheduleEntry | null>(null);
  const [staff, setStaff] = useState<StaffMember[]>([]);

  useEffect(() => {
    async function load() {
      const [scheduleData, staffData] = await Promise.all([
        getSchedule(),
        getStaff(),
      ]);

      // Teachers only ever see entries tied to their own staff_id
      const visibleEntries =
        isTeacher && myStaffId
          ? (scheduleData || []).filter((e: ScheduleEntry) => e.staff_id === myStaffId)
          : scheduleData || [];

      setEntries(visibleEntries);
      setStaff(staffData || []);

      if (visibleEntries.length > 0) {
        setSelectedStudent(visibleEntries[0].student_id);
      }
    }

    load();
  }, [isTeacher, myStaffId]);

  const students = Array.from(
    new Map(
      entries.map((e) => [
        e.student_id,
        {
          id: e.student_id,
          name: e.student_name,
          grade: e.grade,
        },
      ])
    ).values()
  );

  const studentSchedule = entries.filter(
    (e) => e.student_id === selectedStudent
  );

  function getClass(day: string, period: number) {
    return studentSchedule.find(
      (e) => e.day_of_week === day && Number(e.period) === period
    );
  }

  async function saveCell(updated: ScheduleEntry) {
    await updateScheduleEntry(updated.id, updated);

    setEntries((prev) =>
      prev.map((e) => (e.id === updated.id ? updated : e))
    );

    setEditingCell(null);
  }

  return (
    <div style={{ padding: "20px", fontFamily: "Arial" }}>
      <h1 style={{ color: "#313131c7" }}>
        {isTeacher ? "My Students' Schedules" : "Student Schedules"}
      </h1>

      {isTeacher && students.length === 0 && (
        <p>No students are currently assigned to your schedule.</p>
      )}

      {/* Student selector */}
      <select
        value={selectedStudent || ""}
        onChange={(e) => setSelectedStudent(e.target.value || null)}
      >
        <option value="">Loading Students...</option>
        {students.map((s) => (
          <option key={s.id} value={s.id}>
            {s.name}
          </option>
        ))}
      </select>

      {/* GRID */}
      <table style={{ width: "100%", borderSpacing: "8px" }}>
        <thead>
          <tr>
            <th>Period</th>
            {DAYS.map((d) => (
              <th key={d}>{d}</th>
            ))}
          </tr>
        </thead>

        <tbody>
          {PERIODS.map((period) => (
            <tr key={period}>
              <td>{period}</td>

              {DAYS.map((day) => {
                const item = getClass(day, period);
                const isEditing = editingCell?.id === item?.id;

                const cellBackground = !item
                  ? "#ffffff"
                  : item.is_pullout
                  ? "#e78282"
                  : item.is_flex_period
                  ? "#58ee7d"
                  : "#f9fafb";

                return (
                  <td
                    key={day}
                    style={{
                      background: cellBackground,
                      color: "#000000",
                      padding: "8px",
                      minHeight: "80px",
                      border: "1px solid #ddd",
                      cursor: isTeacher ? "default" : "pointer",
                    }}
                    onClick={() => {
                      // Teachers can view but not edit
                      if (item && !isTeacher) {
                        setEditingCell({ ...item });
                      }
                    }}
                  >
                    {!item ? (
                      <span>—</span>
                    ) : isEditing && editingCell && !isTeacher ? (
                      <div>
                        <input
                          value={editingCell.subject || ""}
                          onChange={(e) =>
                            setEditingCell({
                              ...editingCell,
                              subject: e.target.value,
                            })
                          }
                        />

                        <select
                          value={editingCell.staff_id || ""}
                          onChange={(e) => {
                            const selected = staff.find((s) => s.id === e.target.value);

                            setEditingCell({
                              ...editingCell,
                              staff_id: selected?.id,
                              staff_name: selected
                                ? `${selected.first_name} ${selected.last_name}`
                                : "",
                            });
                          }}
                        >
                          <option value="">Unassigned</option>

                          {staff.map((t) => (
                            <option key={t.id} value={t.id}>
                              {t.first_name} {t.last_name} ({t.title})
                            </option>
                          ))}
                        </select>

                        <input
                          value={editingCell.service_type || ""}
                          onChange={(e) =>
                            setEditingCell({
                              ...editingCell,
                              service_type: e.target.value,
                            })
                          }
                        />

                        <label>
                          Pullout:
                          <input
                            type="checkbox"
                            checked={editingCell.is_pullout}
                            onChange={(e) =>
                              setEditingCell({
                                ...editingCell,
                                is_pullout: e.target.checked,
                              })
                            }
                          />
                        </label>

                        <button
                          onClick={(e) => {
                            e.stopPropagation();
                            if (editingCell) {
                              saveCell(editingCell);
                            }
                          }}
                        >
                          Save
                        </button>

                        <button
                          onClick={(e) => {
                            e.stopPropagation();
                            setEditingCell(null);
                          }}
                        >
                          Cancel
                        </button>
                      </div>
                    ) : (
                      <div>
                        <strong>{item.subject}</strong>
                        <div>{item.staff_name}</div>
                        <small>{item.service_type}</small>
                        {item.is_pullout && <div>PULL OUT</div>}
                      </div>
                    )}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}