const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

export interface Alert {
  id: string;
  severity: string;
  rule_triggered: string | null;
  is_resolved: boolean;
  transaction_id: string | null;
  created_at: string;
}

export interface SARReport {
  id: string;
  alert_id: string | null;
  narrative: string | null;
  pdf_path: string | null;
  filed_with_fiu: boolean;
  judge_score: number | null;
  judge_critique: string | null;
  judge_passed: boolean | null;
  created_at: string;
  message?: string;
}

export interface LoginResponse {
  access_token: string;
  token_type: string;
  role: string;
  tenant_id: string;
  user_id: string;
}

class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

function getToken(): string | null {
  return localStorage.getItem("finsight_token");
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const token = getToken();
  const headers: HeadersInit = {
    "Content-Type": "application/json",
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
    ...options.headers,
  };

  const res = await fetch(`${API_BASE_URL}${path}`, { ...options, headers });

  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: res.statusText }));
    throw new ApiError(res.status, body.detail ?? "Request failed");
  }

  return res.json() as Promise<T>;
}

export const api = {
  login: (email: string, password: string) =>
    request<LoginResponse>("/api/v1/auth/login", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    }),

  listAlerts: (resolved = false) =>
    request<Alert[]>(`/api/v1/alerts?resolved=${resolved}`),

  getAlert: (alertId: string) => request<Alert>(`/api/v1/alerts/${alertId}`),

  generateSar: (alertId: string) =>
    request<SARReport>(`/api/v1/alerts/${alertId}/generate-sar`, {
      method: "POST",
    }),

  listSarReports: () => request<SARReport[]>("/api/v1/sar-reports"),

  getSarReport: (sarId: string) => request<SARReport>(`/api/v1/sar-reports/${sarId}`),

  pdfDownloadUrl: (sarId: string) => `${API_BASE_URL}/api/v1/sar-reports/${sarId}/pdf`,
};

export { ApiError, getToken };
