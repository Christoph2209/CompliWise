import { useCallback, useEffect, useState } from "react";
import axios from "axios";
import {
  approvePasswordRequest,
  listPasswordRequests,
  rejectPasswordRequest,
  type PasswordChangeRequest,
} from "../api/account";
import "./Account.css";

const ROLE_LABELS: Record<string, string> = {
  admin: "Administrator",
  principal: "Principal",
  teacher: "Teacher",
  aide: "Aide",
};

function formatWhen(iso: string | null) {
  return iso ? new Date(iso + (iso.endsWith("Z") ? "" : "Z")).toLocaleString() : "—";
}

export default function PasswordRequestsPage() {
  const [view, setView] = useState<"pending" | "all">("pending");
  const [rows, setRows] = useState<PasswordChangeRequest[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [notes, setNotes] = useState<Record<string, string>>({});

  const load = useCallback(async () => {
    try {
      setRows(await listPasswordRequests(view));
      setError(null);
    } catch {
      setError("Couldn't load password requests.");
    } finally {
      setLoading(false);
    }
  }, [view]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- fetch-on-mount + polling, load() is async
    load();
    const interval = setInterval(load, 30000);
    return () => clearInterval(interval);
  }, [load]);

  async function decide(req: PasswordChangeRequest, action: "approve" | "reject") {
    const who = req.user?.full_name || req.user?.email || "this user";
    if (
      action === "approve" &&
      !window.confirm(`Approve the new password for ${who}? They'll be signed out and must log in with it.`)
    ) {
      return;
    }
    setBusyId(req.id);
    setError(null);
    setNotice(null);
    try {
      const note = notes[req.id]?.trim();
      if (action === "approve") {
        await approvePasswordRequest(req.id, note);
        setNotice(`Approved. ${who}'s new password is now active.`);
      } else {
        await rejectPasswordRequest(req.id, note);
        setNotice(`Rejected. ${who} keeps their current password.`);
      }
      await load();
    } catch (err) {
      const detail = axios.isAxiosError(err) ? err.response?.data?.detail : null;
      setError(typeof detail === "string" ? detail : "That didn't work. Try again.");
      await load();
    } finally {
      setBusyId(null);
    }
  }

  return (
    <div className="account-page account-page--wide">
      <header className="account-header">
        <h1>Password Requests</h1>
        <p>
          Staff password changes wait here until you approve them. Before approving, confirm the
          request with the person directly — a request you didn't expect could mean someone else
          is using their account.
        </p>
      </header>

      <div className="account-tabs" role="tablist">
        <button role="tab" aria-selected={view === "pending"} onClick={() => setView("pending")}>
          Pending
        </button>
        <button role="tab" aria-selected={view === "all"} onClick={() => setView("all")}>
          History
        </button>
      </div>

      {error && <div className="account-banner account-banner--error">{error}</div>}
      {notice && <div className="account-banner account-banner--ok">{notice}</div>}

      {loading ? (
        <p className="account-hint">Loading…</p>
      ) : rows.length === 0 ? (
        <div className="account-card account-empty">
          {view === "pending" ? "No password changes waiting for approval." : "No password requests yet."}
        </div>
      ) : (
        <div className="account-list">
          {rows.map((req) => (
            <article key={req.id} className="account-card account-request">
              <div className="account-request-who">
                <strong>{req.user?.full_name || req.user?.email}</strong>
                {req.user?.full_name && <span>{req.user.email}</span>}
                <span className="account-pill">{ROLE_LABELS[req.user?.role ?? ""] ?? req.user?.role}</span>
              </div>
              <div className="account-request-meta">
                <span>Requested {formatWhen(req.requested_at)}</span>
                {req.status !== "pending" && (
                  <span>
                    <span className={`account-pill account-pill--${req.status}`}>{req.status}</span>
                    {req.reviewed_by ? ` by ${req.reviewed_by}` : ""} · {formatWhen(req.reviewed_at)}
                  </span>
                )}
                {req.review_note && <em>“{req.review_note}”</em>}
              </div>

              {req.status === "pending" && (
                <div className="account-request-actions">
                  <input
                    type="text"
                    placeholder="Note (optional, the user sees it)"
                    maxLength={500}
                    value={notes[req.id] ?? ""}
                    onChange={(e) => setNotes((n) => ({ ...n, [req.id]: e.target.value }))}
                  />
                  <button
                    className="account-btn"
                    disabled={busyId === req.id}
                    onClick={() => decide(req, "approve")}
                  >
                    Approve
                  </button>
                  <button
                    className="account-btn account-btn--danger"
                    disabled={busyId === req.id}
                    onClick={() => decide(req, "reject")}
                  >
                    Reject
                  </button>
                </div>
              )}
            </article>
          ))}
        </div>
      )}
    </div>
  );
}
