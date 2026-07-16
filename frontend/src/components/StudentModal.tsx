import React, { useMemo } from "react";

type ScheduleEntry = {
  day_of_week: string;
  period: number | string;
  subject?: string;
  service_type?: string;
  staff_id?: string;
  staff_name?: string;
  student_name?: string;
  student_id?: string;
};

type Props = {
  selectedSlot: ScheduleEntry | null;
  teacherSchedule: ScheduleEntry[];
  onClose: () => void;
};

export default function StudentModal({
  selectedSlot,
  teacherSchedule,
  onClose,
}: Props) {
 const students = useMemo(() => {
  if (!selectedSlot) return [];

  return teacherSchedule.filter(
    (student) =>
      student.day_of_week === selectedSlot.day_of_week &&
      Number(student.period) === Number(selectedSlot.period)
  );
}, [teacherSchedule, selectedSlot]);

if (!selectedSlot) {
  return null; // early return now happens AFTER all hooks have run
}

  return (
    <div
      onClick={onClose}
      style={{
        position: "fixed",
        inset: 0,
        background: "rgba(0,0,0,0.45)",
        display: "flex",
        justifyContent: "center",
        alignItems: "center",
        zIndex: 9999,
      }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{
          width: "420px",
          maxHeight: "75vh",
          overflowY: "auto",
          background: "#fff",
          borderRadius: "14px",
          padding: "20px",
          boxShadow: "0 15px 40px rgba(0,0,0,0.3)",
        }}
      >
        {/* Header */}
        <div style={{ marginBottom: "10px" }}>
          <button
            onClick={onClose}
            style={{
              float: "right",
              border: "none",
              background: "#eee",
              padding: "6px 10px",
              borderRadius: "6px",
              cursor: "pointer",
              color: "#000000",
            }}
          >
            ✕
          </button>

          <h2 style={{ margin: 0, color: "#000000" }}>{selectedSlot.subject || "Class"}</h2>

          <p style={{ margin: "5px 0", color: "#555" }}>
            {selectedSlot.day_of_week} • Period {selectedSlot.period}
          </p>

          {selectedSlot.service_type && (
            <span style={{ fontSize: "12px", color: "#777" }}>
              {selectedSlot.service_type}
            </span>
          )}
        </div>

        <hr />

        {/* Students */}
        <h3 style={{ marginTop: "10px" }}>Students</h3>

        {students.length === 0 ? (
          <p style={{ color: "#000000" }}>No students in this class</p>
        ) : (
          <ul style={{ paddingLeft: "18px", color: "#000000" }}>
            {students.map((student, index) => (
              <li key={index} style={{ marginBottom: "6px" }}>
                {student.student_name || student.student_id}
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}