import { useCallback, useEffect, useState } from "react";
import axios from "axios";
import { useAuth } from "../context/authContext";
import {
  cancelMyPasswordRequest,
  changeMyPassword,
  getMyPasswordRequest,
  MIN_PASSWORD_LENGTH,
  type MyPasswordRequestInfo,
} from "../api/account";
import "./Account.css";

const ROLE_LABELS: Record<string, string> = {
  admin: "Administrator",
  principal: "Principal",
  teacher: "Teacher",
  aide: "Aide",
};

function errorMessage(err: unknown, fallback: string) {
  if (axios.isAxiosError(err)) {
    const detail = err.response?.data?.detail;
    if (typeof detail === "string") return detail;
  }
  return fallback;
}

function formatWhen(iso: string | null) {
  return iso ? new Date(iso + (iso.endsWith("Z") ? "" : "Z")).toLocaleString() : "";
}

export default function AccountPage() {
  const { user } = useAuth();
  const [info, setInfo] = useState<MyPasswordRequestInfo | null>(null);
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      setInfo(await getMyPasswordRequest());
    } catch (err) {
      setError(errorMessage(err, "Couldn't load your account details."));
    }
  }, []);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- fetch-on-mount, load() is async
    load();
  }, [load]);

  const pending = info?.request?.status === "pending" ? info.request : null;
  const lastDecision =
    info?.request && info.request.status !== "pending" && info.request.status !== "cancelled"
      ? info.request
      : null;
  const needsApproval = info?.requires_approval ?? true;

  const tooShort = next.length > 0 && next.length < MIN_PASSWORD_LENGTH;
  const mismatch = confirm.length > 0 && next !== confirm;
  const canSubmit =
    !busy && current.length > 0 && next.length >= MIN_PASSWORD_LENGTH && next === confirm;

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!canSubmit) return;
    setError(null);
    setNotice(null);
    setBusy(true);
    try {
      const result = await changeMyPassword(current, next);
      setCurrent("");
      setNext("");
      setConfirm("");
      setNotice(
        result.status === "changed"
          ? "Your password has been changed. Any other devices you were signed in on have been signed out."
          : "Request sent. An administrator needs to approve it before your new password works — until then, keep using your current one."
      );
      await load();
    } catch (err) {
      setError(errorMessage(err, "Couldn't update your password."));
    } finally {
      setBusy(false);
    }
  }

  async function handleCancel() {
    setError(null);
    setNotice(null);
    setBusy(true);
    try {
      await cancelMyPasswordRequest();
      setNotice("Your request was withdrawn. Your current password is unchanged.");
      await load();
    } catch (err) {
      setError(errorMessage(err, "Couldn't withdraw the request."));
    } finally {
      setBusy(false);
    }
  }

  if (!user) return null;

  const displayName =
    user.full_name ||
    (user.staff_member ? `${user.staff_member.first_name} ${user.staff_member.last_name}` : null) ||
    user.email;

  return (
    <div className="account-page">
      <header className="account-header">
        <h1>My Account</h1>
        <p>Your sign-in details for CompliWise.</p>
      </header>

      <section className="account-card">
        <h2>Profile</h2>
        <dl className="account-details">
          <div>
            <dt>Name</dt>
            <dd>{displayName}</dd>
          </div>
          <div>
            <dt>Email</dt>
            <dd>{user.email}</dd>
          </div>
          <div>
            <dt>Role</dt>
            <dd>{ROLE_LABELS[user.role] ?? user.role}</dd>
          </div>
          {user.staff_member && (
            <div>
              <dt>Linked staff record</dt>
              <dd>
                {user.staff_member.first_name} {user.staff_member.last_name}
              </dd>
            </div>
          )}
        </dl>
      </section>

      <section className="account-card">
        <h2>Password</h2>
        {needsApproval && (
          <p className="account-hint">
            For security, password changes are reviewed by your school's administrator. Your new
            password starts working once it's approved, and you'll be asked to sign in again.
          </p>
        )}

        {error && <div className="account-banner account-banner--error">{error}</div>}
        {notice && <div className="account-banner account-banner--ok">{notice}</div>}

        {pending && (
          <div className="account-status account-status--pending">
            <div>
              <strong>Waiting for approval</strong>
              <span>Requested {formatWhen(pending.requested_at)}</span>
            </div>
            <button type="button" className="account-btn account-btn--ghost" onClick={handleCancel} disabled={busy}>
              Withdraw request
            </button>
          </div>
        )}

        {!pending && lastDecision && (
          <div className={`account-status account-status--${lastDecision.status}`}>
            <div>
              <strong>
                Last request {lastDecision.status}
                {lastDecision.reviewed_by ? ` by ${lastDecision.reviewed_by}` : ""}
              </strong>
              <span>{formatWhen(lastDecision.reviewed_at)}</span>
              {lastDecision.review_note && <em>“{lastDecision.review_note}”</em>}
            </div>
          </div>
        )}

        <form className="account-form" onSubmit={handleSubmit}>
          {pending && (
            <p className="account-hint">Submitting again replaces the request that's waiting.</p>
          )}
          <label>
            Current password
            <input
              type="password"
              autoComplete="current-password"
              value={current}
              onChange={(e) => setCurrent(e.target.value)}
            />
          </label>
          <label>
            New password
            <input
              type="password"
              autoComplete="new-password"
              value={next}
              onChange={(e) => setNext(e.target.value)}
              aria-invalid={tooShort}
            />
            <small className={tooShort ? "account-field-error" : undefined}>
              At least {MIN_PASSWORD_LENGTH} characters.
            </small>
          </label>
          <label>
            Confirm new password
            <input
              type="password"
              autoComplete="new-password"
              value={confirm}
              onChange={(e) => setConfirm(e.target.value)}
              aria-invalid={mismatch}
            />
            {mismatch && <small className="account-field-error">Passwords don't match.</small>}
          </label>
          <div className="account-actions">
            <button type="submit" className="account-btn" disabled={!canSubmit}>
              {busy ? "Saving…" : needsApproval ? "Request password change" : "Change password"}
            </button>
          </div>
        </form>
      </section>
    </div>
  );
}
