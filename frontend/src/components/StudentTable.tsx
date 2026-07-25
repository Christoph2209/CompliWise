interface Props {

  students:any[];

  onSelect:(student:any)=>void;

}


export default function StudentTable({
  students,
  onSelect
}:Props){


return (

<table>

<thead>

<tr>

<th>Name</th>
<th>Grade</th>
<th>Homeroom</th>
<th>MTSS</th>
<th>IEP</th>

</tr>

</thead>



<tbody>


{students.map(student=>(


<tr

key={student.id}

onClick={() =>
  onSelect(student)
}

style={{
 cursor:"pointer"
}}

>


<td>

{student.first_name}
{" "}
{student.last_name}

</td>



<td>
{student.grade}
</td>

<td>
{student.enl_minutes_required}
</td>

<td>
{student.homeroom}
</td>



<td>
{student.mtss_tier}
</td>



<td>

{
student.has_iep
? "Yes"
: "No"
}

</td>


</tr>


))}



</tbody>


</table>

);


}