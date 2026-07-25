export type Role =
  | "admin"
  | "principal"
  | "teacher"
  | "aide";


export interface User {
  id: string;
  role: Role;
  full_name: string;
  school_id: string;
  staff_member: {
    id: string;
    first_name: string;
    last_name: string;
  } | null;
}