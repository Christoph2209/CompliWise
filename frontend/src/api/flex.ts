import { api } from "./clients";

export async function getFlexGroups() {
  const response = await api.get("/flex_groups");
  return response.data;
}