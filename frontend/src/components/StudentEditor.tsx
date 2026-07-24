import "./StudentEditor.css";

interface Props {
  student:any;
  setStudent:(student:any)=>void;
  onSave:()=>void;
  onCancel:()=>void;
}

export default function StudentEditor({
  student,
  setStudent,
  onSave,
  onCancel
}:Props){


if(!student)
  return null;



function update(
  field:string,
  value:any
){

  setStudent({
    ...student,
    [field]:value
  });

}



return (

<div className="modal-backdrop">


  <div className="student-modal">


    <div className="modal-header">

      <h2>
        Edit Student
      </h2>

      <button onClick={onCancel}>
        X
      </button>

    </div>



    <div className="modal-body">



      <label>
        First Name
      </label>

      <input

        value={student.first_name}

        onChange={(e)=>
          update(
            "first_name",
            e.target.value
          )
        }

      />



      <label>
        Last Name
      </label>

      <input

        value={student.last_name}

        onChange={(e)=>
          update(
            "last_name",
            e.target.value
          )
        }

      />



      <label>
        Grade
      </label>

      <input

        value={student.grade}

        onChange={(e)=>
          update(
            "grade",
            e.target.value
          )
        }

      />




      <label>
        Homeroom
      </label>

      <input

        value={
          student.homeroom || ""
        }

        onChange={(e)=>
          update(
            "homeroom",
            e.target.value
          )
        }

      />

    <label>
        ENL Minutes Required
      </label>

      <input

        value={
          student.enl_minutes_required || ""
        }

        onChange={(e)=>
          update(
            "enl_minutes_required",
            e.target.value
          )
        }

      />



      <label>
        MTSS Tier
      </label>


      <select

        value={student.mtss_tier}

        onChange={(e)=>
          update(
            "mtss_tier",
            e.target.value
          )
        }

      >

        <option value="1">
          Tier 1
        </option>

        <option value="2">
          Tier 2
        </option>

        <option value="3">
          Tier 3
        </option>

      </select>




      <label>

        Has IEP

        <input

          type="checkbox"

          checked={
            student.has_iep
          }

          onChange={(e)=>
            update(
              "has_iep",
              e.target.checked
            )
          }

        />

      </label>




      <label>
        ENL Level
      </label>


      <input

        value={
          student.enl_level || ""
        }

        onChange={(e)=>
          update(
            "enl_level",
            e.target.value
          )
        }

      />



      <label>
        ENL Minutes Required
      </label>


      <input

        value={
          student.enl_minutes_required || ""
        }

        onChange={(e)=>
          update(
            "enl_minutes_required",
            e.target.value
          )
        }

      />




    </div>



    <div className="modal-footer">


      <button onClick={onSave}>
        Save
      </button>


      <button onClick={onCancel}>
        Cancel
      </button>


    </div>



  </div>


</div>

);

}