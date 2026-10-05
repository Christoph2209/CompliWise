import {
  createContext,
  useContext,
  useState,
  useEffect,
} from "react";

import type { User } from "./authTypes";
import { api } from "../api/clients";
import { getCurrentUser } from "../api/auth";

type AuthContextType = {
  user: User | null;
  loading: boolean;
  login: (email: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
};

const AuthContext = createContext<AuthContextType | null>(null);

// Lets tabs in the same browser tell each other the logged-in user changed,
// so an old tab reloads instead of silently acting as the new user.
const authChannel =
  typeof BroadcastChannel !== "undefined"
    ? new BroadcastChannel("compliwise-auth")
    : null;

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    getCurrentUser()
      .then((freshUser) => setUser(freshUser))
      .catch(() => setUser(null))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    if (!authChannel) return;
    const handleAuthChange = () => window.location.reload();
    authChannel.addEventListener("message", handleAuthChange);
    return () => authChannel.removeEventListener("message", handleAuthChange);
  }, []);

  async function login(email: string, password: string) {
    await api.post("/login", { email, password }); // throws on 401
    const freshUser = await getCurrentUser();
    setUser(freshUser);
    authChannel?.postMessage("auth-changed");
  }

  async function logout() {
    try {
      await api.post("/logout");
    } finally {
      setUser(null);
      authChannel?.postMessage("auth-changed");
    }
  }

  return (
    <AuthContext.Provider value={{ user, loading, login, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

// Kept next to the provider it reads; only affects dev hot reload.
// eslint-disable-next-line react-refresh/only-export-components
export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error("useAuth must be used inside AuthProvider");
  }
  return context;
}