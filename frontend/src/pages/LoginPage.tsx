import { useState } from "react";
import { useAuth } from "../context/authContext";
import { useNavigate } from "react-router-dom";

export default function Login() {
  const { login } = useAuth();
  const navigate = useNavigate();

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");

  const handleLogin = async () => {
    try {
      await login(email, password);
      navigate("/");
    } catch (err) {
      alert("Invalid login");
    }
  };

  return (
    <div>
      <h2>Login</h2>

      <input
        placeholder="email"
        value={email}
        onChange={(e) => setEmail(e.target.value)}
      />

      <input
        placeholder="password"
        type="password"
        value={password}
        onChange={(e) => setPassword(e.target.value)}
      />

      <button onClick={handleLogin}>Login</button>
    </div>
  );
}