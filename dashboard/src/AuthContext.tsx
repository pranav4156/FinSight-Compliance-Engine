import { createContext, useContext, useState, type ReactNode } from "react";
import { api } from "./api";

interface AuthState {
  token: string | null;
  role: string | null;
  login: (email: string, password: string) => Promise<void>;
  logout: () => void;
}

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [token, setToken] = useState<string | null>(localStorage.getItem("finsight_token"));
  const [role, setRole] = useState<string | null>(localStorage.getItem("finsight_role"));

  async function login(email: string, password: string) {
    const res = await api.login(email, password);
    localStorage.setItem("finsight_token", res.access_token);
    localStorage.setItem("finsight_role", res.role);
    setToken(res.access_token);
    setRole(res.role);
  }

  function logout() {
    localStorage.removeItem("finsight_token");
    localStorage.removeItem("finsight_role");
    setToken(null);
    setRole(null);
  }

  return (
    <AuthContext.Provider value={{ token, role, login, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
