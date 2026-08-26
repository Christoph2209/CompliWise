import { useEffect, useState } from "react";
import { Navigate, Outlet } from "react-router-dom";
// Match whatever import path you're actually using for the shared axios
// instance elsewhere in the app.
import {api} from "../api/clients";

type SetupStatus = {
  database_ready: boolean;
  setup_complete: boolean;
};

/**
 * Layout route -- wrap it around every route except /setup itself
 * (via <Route element={<SetupGate />}>...child routes...</Route>).
 *
 * While the check is in flight, renders nothing rather than flashing
 * the app shell or the login page first. Fails "closed" (treats an
 * unreachable backend as incomplete, not complete) so a network blip
 * sends people to the wizard rather than a broken protected page.
 */
export default function SetupGate() {
  const [status, setStatus] = useState<"checking" | "complete" | "incomplete">("checking");

  useEffect(() => {
    let ignore = false;

    (async () => {
      try {
        const { data } = await api.get<SetupStatus>("/setup/status");
        if (ignore) return;
        setStatus(data.setup_complete ? "complete" : "incomplete");
      } catch {
        if (!ignore) setStatus("incomplete");
      }
    })();

    return () => {
      ignore = true;
    };
  }, []);

  if (status === "checking") return null;
  if (status === "incomplete") return <Navigate to="/setup" replace />;

  return <Outlet />;
}