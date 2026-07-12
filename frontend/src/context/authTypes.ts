export type Role =
  | "admin"
  | "principal"
  | "teacher"
  | "aide";


export type User = {
  user_id: string;
  role: Role;
  staff_id?: string;
  staff_member: StaffMember | null;
};