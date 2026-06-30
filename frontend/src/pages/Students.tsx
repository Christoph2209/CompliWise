import { useEffect, useState } from "react";
import { getStudents, updateStudent } from "../api/students";
import "../components/StudentEditor.css";

export default function Students() {

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
    const data = await getStudents();
    setStudents(data);
  }

  

async function saveStudent() {
  try {
    const payload = {
      first_name: selectedStudent.first_name,
      last_name: selectedStudent.last_name,
      grade: Number(selectedStudent.grade),
      homeroom: selectedStudent.homeroom,
      has_iep: Boolean(selectedStudent.has_iep),
      mtss_tier: selectedStudent.mtss_tier ? Number(selectedStudent.mtss_tier) : null,
    };

    const res = await updateStudent(selectedStudent.id, payload);
    console.log("SUCCESS:", res);

    await loadStudents();
    setSelectedStudent(null);

  } catch (err: any) {
    console.log("FULL ERROR RESPONSE:");
    console.log(err.response?.data);
    console.log(err.response?.status);
    console.log(err.message);
  }
}

  const filteredStudents = students.filter(student => {

    const name =
      `${student.first_name} ${student.last_name}`
      .toLowerCase();


    return (
      name.includes(search.toLowerCase()) &&
      (iepFilter === "" ||
        student.has_iep.toString() === iepFilter) &&
      (tierFilter === "" ||
        student.mtss_tier === tierFilter)
    );

  });



  return (
    <div>

      <h1>Students</h1>


      {/* Filters */}

      <input
        placeholder="Search student..."
        value={search}
        onChange={
          e => setSearch(e.target.value)
        }
      />


      <select
        onChange={e=>setIepFilter(e.target.value)}
      >
        <option value="">
          All IEP Status
        </option>

        <option value="true">
          Has IEP
        </option>

        <option value="false">
          No IEP
        </option>

      </select>


      <select
        onChange={e=>setTierFilter(e.target.value)}
      >

        <option value="">
          All MTSS
        </option>

        <option value="tier_1">
          Tier 1
        </option>

        <option value="tier_2">
          Tier 2
        </option>

        <option value="tier_3">
          Tier 3
        </option>

      </select>



     <div className="student-grid">
  {filteredStudents.map(student => (
    <div
      key={student.id}
      className="student-card"
      onClick={() => setSelectedStudent(student)}
    >
      <div className="student-name">
        {student.first_name} {student.last_name}
      </div>

      <div className="student-info">
        <div><strong>Grade:</strong> {student.grade}</div>
        <div><strong>Homeroom:</strong> {student.homeroom || "N/A"}</div>
        <div><strong>Tier:</strong> {student.mtss_tier || "None"}</div>
        <div>
          <strong>IEP:</strong>{" "}
          {student.has_iep ? "Yes" : "No"}
        </div>
      </div>
    </div>
  ))}
</div>



      {/* EDIT PANEL */}


      {selectedStudent && (
  <div className="modal-backdrop"
   onClick={() => setSelectedStudent(null)}>
    <div className="student-modal"
     onClick={(e) => e.stopPropagation()}>
      
      <h2>Edit Student</h2>

      <div className="modal-body">

        <input
          value={selectedStudent.first_name}
          onChange={e =>
            setSelectedStudent({
              ...selectedStudent,
              first_name: e.target.value
            })
          }
        />

        <input
          value={selectedStudent.last_name}
          onChange={e =>
            setSelectedStudent({
              ...selectedStudent,
              last_name: e.target.value
            })
          }
        />

        <input
          value={selectedStudent.grade}
          onChange={e =>
            setSelectedStudent({
              ...selectedStudent,
              grade: e.target.value
            })
          }
        />

        <input
          value={selectedStudent.homeroom || ""}
          onChange={e =>
            setSelectedStudent({
              ...selectedStudent,
              homeroom: e.target.value
            })
          }
        />

        <input
          value={selectedStudent.enl_minutes_required || "None"}
          onChange={e =>
            setSelectedStudent({
              ...selectedStudent,
              enl_minutes_required: e.target.value
            })
          }
        />

        <label>
          IEP:
          <input
            type="checkbox"
            checked={selectedStudent.has_iep}
            onChange={e =>
              setSelectedStudent({
                ...selectedStudent,
                has_iep: e.target.checked
              })
            }
          />
        </label>

        <button onClick={saveStudent}>Save</button>
        <button onClick={() => setSelectedStudent(null)}>
          Cancel
        </button>

      </div>
    </div>
  </div>
)}


    </div>
  );
}