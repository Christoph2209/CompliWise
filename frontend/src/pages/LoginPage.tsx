import { useState } from "react";
import { useAuth } from "../context/authContext";
import { useNavigate } from "react-router-dom";
import "./LoginPage.css";

const DEMO_ACCOUNTS = [
  {
    role: "Principal",
    hint: "Build and edit schedules",
    username: "principal@school.com",
    password: "password1234",
  },
  {
    role: "Teacher",
    hint: "See your own classes",
    username: "linda@school.com",
    password: "yellowbanana456",
  },
];

export default function Login() {
  const { login } = useAuth();
  const navigate = useNavigate();

  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);

  const handleLogin = async (user = username, pass = password) => {
    setError("");
    setIsSubmitting(true);
    try {
      await login(user, pass);
      navigate("/");
    } catch (error) {
      setError("That username or password doesn't match. Give it another try.\n" + (error instanceof Error ? ` (${error.message})` : ""));
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleDemoLogin = (account: (typeof DEMO_ACCOUNTS)[number]) => {
    setUsername(account.username);
    setPassword(account.password);
    handleLogin(account.username, account.password);
  };

  const handleKeyDown =(e: React.KeyboardEvent) => {
    if (e.key === "Enter") {
      handleLogin();
    }
  };

  return (
    <div className="login-page">
      <div className="login-card">
        <h2 className="login-title">Welcome back</h2>
        <p className="login-subtitle">Log in to get to your schedule.</p>

        <div className="login-field">
          <label htmlFor="username">Username</label>
          <input
            id="username"
            placeholder="e.g. jsmith"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            onKeyDown={handleKeyDown}
            autoComplete="username"
          />
        </div>

        <div className="login-field">
          <label htmlFor="password">Password</label>
          <input
            id="password"
            placeholder="********"
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            onKeyDown={handleKeyDown}
            autoComplete="current-password"
          />
        </div>

        {error && <p className="login-error">{error}</p>}

        <button
          className="login-button"
          onClick={() => handleLogin()}
          disabled={isSubmitting}
        >
          {isSubmitting ? "Logging in..." : "Log in"}
        </button>

        <div className="login-demo">
          <p className="login-demo-title">Just looking around?</p>
          <p className="login-demo-text">
            This is a demo with sample data. Pick a role to log in and explore.
          </p>
          <div className="login-demo-buttons">
            {DEMO_ACCOUNTS.map((account) => (
              <button
                key={account.username}
                className="login-demo-button"
                onClick={() => handleDemoLogin(account)}
                disabled={isSubmitting}
              >
                <span className="login-demo-role">{account.role}</span>
                <span className="login-demo-hint">{account.hint}</span>
              </button>
            ))}
          </div>
        </div>

        {/* Group's forgot-password decision pending -- wire this up once finalized */}
        {/* <a className="login-forgot" href="#">Forgot your password?</a> */}
      </div>
    </div>
  );
} 