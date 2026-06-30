import { api } from "./clients";

export async function getStudents() {
  const response = await api.get("/students");
  return response.data.students;
}

export async function updateStudent(id: string, student: any) {
  const response = await api.put(`/students/${id}`, student);
  return response.data.student;
}