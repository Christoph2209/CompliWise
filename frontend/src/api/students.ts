import { api } from "./clients";

export async function getStudents() {
  const response = await api.get("/students");
  return response.data.students;
}

export async function updateStudent(id: string, student: any) {
  const response = await api.put(`/students/${id}`, student);
  return response.data.student;
}

export async function getMyStudents() {
  const res = await api.get("/me/students"); // adjust to match your existing fetch/client wrapper
  return res.data;
}