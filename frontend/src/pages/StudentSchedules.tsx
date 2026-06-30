import { useEffect, useState } from "react";
import { getSchedule, updateScheduleEntry } from "../api/schedule";
import { getStaff } from "../api/staff";

const DAYS = ["monday", "tuesday", "wednesday", "thursday", "friday"];
const PERIODS = [1, 2, 3, 4, 5, 6, 7, 8, 9];

export default function StudentSchedules() {
  const [entries, setEntries] = useState<any[]>([]);
  const [selectedStudent, setSelectedStudent] = useState("");
  const [editingCell, setEditingCell] = useState<any>(null);
  const [staff, setStaff] = useState<any[]>([]);
  useEffect(() => {
    getSchedule().then(setEntries);
  }, []);

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

  async function saveCell(updated: any) {
    await updateScheduleEntry(updated.id, updated);

    setEntries((prev) =>
      prev.map((e) => (e.id === updated.id ? updated : e))
    );

    setEditingCell(null);
  }

  useEffect(() => {
  async function load() {
    const [scheduleData, staffData] = await Promise.all([
      getSchedule(),
      getStaff(),
    ]);

    setEntries(scheduleData || []);
    setStaff(staffData || []);
  }

  load();
}, []);
  return (
    <div style={{ padding: "20px", fontFamily: "Arial" }}>
      <h1>Student Schedules</h1>

      {/* Student selector */}
      <select
        value={selectedStudent}
        onChange={(e) => setSelectedStudent(e.target.value)}
      >
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
                const isFlex = item?.is_flex_period;
                return (
                  <td
                    key={day}
                    style={{
                      background: "#f9fafb",
                      padding: "8px",
                      minHeight: "80px",
                      border: "1px solid #ddd",
                      cursor: "pointer",
                    }}
                    onClick={() => item && setEditingCell(item)}
                  >
                    {!item ? (
                      <span>—</span>
                    ) : isEditing ? (
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

                        <button onClick={() => saveCell(editingCell)}>
                          Save
                        </button>

                        <button onClick={() => setEditingCell(null)}>
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