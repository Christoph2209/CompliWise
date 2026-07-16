import {
  createContext,
  useContext,
  useState,
  useEffect,
} from "react";

import type { User } from "./authTypes";
import { getCurrentUser } from "../api/auth"; // wherever getCurrentUser lives

type AuthContextType = {
  user: User | null;
  loading: boolean;
  login: (email: string, password: string) => Promise<void>;
  logout: () => void;
};

const AuthContext = createContext<AuthContextType | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    getCurrentUser()
      .then((freshUser) => setUser(freshUser))
      .catch(() => setUser(null))
      .finally(() => setLoading(false));
  }, []);

  async function login(email: string, password: string) {
    const response = await fetch("http://localhost:8000/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password }),
    });

    if (!response.ok) {
      throw new Error("Login failed");
    }

    // trust /me as the source of truth, not whatever /login returns
    const freshUser = await getCurrentUser();
    setUser(freshUser);
  }

  function logout() {
    setUser(null);
    // if you're using a cookie-based session, also hit a /logout endpoint
    // to actually invalidate it server-side, not just clear local state
  }

  return (
    <AuthContext.Provider value={{ user, loading, login, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error("useAuth must be used inside AuthProvider");
  }
  return context;
}