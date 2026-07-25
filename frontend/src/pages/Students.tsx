import { useEffect, useState } from "react";
import { getStudents, getMyStudents, updateStudent } from "../api/students";
import { useAuth } from "../context/authContext";
import StudentEditor from "../components/StudentEditor";
import "../components/StudentEditor.css";

export default function Students() {
  const { user } = useAuth();
  const isTeacher = user?.role === "teacher";

  const [students, setStudents] = useState<any[]>([]);
  const [selectedStudent, setSelectedStudent] = useState<any>(null);

  const [search, setSearch] = useState("");
  const [iepFilter, setIepFilter] = useState("");
  const [tierFilter, setTierFilter] = useState("");

  useEffect(() => {
    loadStudents();
  }, []);

  useEffect(() => {
    if (selectedStudent) {
      document.body.style.overflow = "hidden";
    } else {
      document.body.style.overflow = "auto";
    }
  }, [selectedStudent]);

  async function loadStudents() {
    if (isTeacher) {
      // /me/students groups by class, so flatten + dedupe into a plain roster
      const classes = await getMyStudents();
      const roster = new Map();

      for (const cls of classes || []) {
        for (const s of cls.students || []) {
          roster.set(s.id, s);
        }
      }

      setStudents(Array.from(roster.values()));
    } else {
      const data = await getStudents();
      setStudents(data);
    }
  }

  async function saveStudent() {
    // NOTE: grade and mtss_tier are stored as STRINGS ("K", "1" .. "5"
    // and "tier_1"/"tier_2"/"tier_3"), never numbers. Number("K") and
    // Number("tier_1") both evaluate to NaN, which serializes to null
    // over the wire -- that was silently wiping grade/tier on save.
    // Send them through untouched.
    const payload = {
      first_name: selectedStudent.first_name,
      last_name: selectedStudent.last_name,
      grade: selectedStudent.grade || null,
      homeroom: selectedStudent.homeroom,
      has_iep: Boolean(selectedStudent.has_iep),
      mtss_tier: selectedStudent.mtss_tier || null,
      enl_level: selectedStudent.enl_level || null,
    };

    // Let errors propagate to StudentEditor, which surfaces them in
    // the modal instead of only logging to the console.
    await updateStudent(selectedStudent.id, payload);
    await loadStudents();
    setSelectedStudent(null);
  }

  const filteredStudents = students.filter((student) => {
    const name = `${student.first_name} ${student.last_name}`.toLowerCase();

    return (
      name.includes(search.toLowerCase()) &&
      (iepFilter === "" || student.has_iep.toString() === iepFilter) &&
      (tierFilter === "" || student.mtss_tier === tierFilter)
    );
  });

  return (
    <div className="students-page">
      <h1>{isTeacher ? "My Students" : "Students"}</h1>

      <div className="students-filters">
        <input
          className="students-search"
          placeholder="Search student..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />

        <select
          className="students-filter-select"
          value={iepFilter}
          onChange={(e) => setIepFilter(e.target.value)}
        >
          <option value="">All IEP Status</option>
          <option value="true">Has IEP</option>
          <option value="false">No IEP</option>
        </select>

        <select
          className="students-filter-select"
          value={tierFilter}
          onChange={(e) => setTierFilter(e.target.value)}
        >
          <option value="">All MTSS</option>
          <option value="tier_1">Tier 1</option>
          <option value="tier_2">Tier 2</option>
          <option value="tier_3">Tier 3</option>
        </select>
      </div>

      {isTeacher && filteredStudents.length === 0 && (
        <p className="students-empty">
          No students are currently assigned to your schedule.
        </p>
      )}

      <div className="student-grid">
        {filteredStudents.map((student) => (
          <div
            key={student.id}
            className="student-card"
            onClick={() => setSelectedStudent(student)}
          >
            <div className="student-name">
              {student.first_name} {student.last_name}
            </div>

            <div className="student-info">
              <div>
                <span className="student-info-label">Grade</span>
                <span className="student-info-value">
                  {student.grade || "—"}
                </span>
              </div>
              <div>
                <span className="student-info-label">Homeroom</span>
                <span className="student-info-value">
                  {student.homeroom || "N/A"}
                </span>
              </div>
              <div>
                <span className="student-info-label">Tier</span>
                <span className="student-info-value">
                  {student.mtss_tier || "None"}
                </span>
              </div>
              <div>
                <span className="student-info-label">IEP</span>
                <span
                  className={
                    "student-badge " +
                    (student.has_iep ? "student-badge-yes" : "student-badge-no")
                  }
                >
                  {student.has_iep ? "Yes" : "No"}
                </span>
              </div>
              <div>
                <span className="student-info-label">ENL</span>
                <span className="student-info-value">
                  {student.enl_level || "None"}
                </span>
              </div>
            </div>
          </div>
        ))}
      </div>

      {selectedStudent && (
        <StudentEditor
          student={selectedStudent}
          setStudent={setSelectedStudent}
          onSave={saveStudent}
          onCancel={() => setSelectedStudent(null)}
          readOnly={isTeacher}
        />
      )}
    </div>
  );
}