import { useEffect, useState } from "react";
import { api, ApiError, type Alert, type SARReport } from "./api";
import { useAuth } from "./AuthContext";

export function Dashboard() {
  const { role, logout } = useAuth();
  const [alerts, setAlerts] = useState<Alert[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedAlertId, setSelectedAlertId] = useState<string | null>(null);
  const [sar, setSar] = useState<SARReport | null>(null);
  const [generating, setGenerating] = useState(false);

  async function loadAlerts() {
    setLoading(true);
    setError(null);
    try {
      const data = await api.listAlerts(false);
      setAlerts(data);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to load alerts");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadAlerts();
  }, []);

  async function handleGenerateSar(alertId: string) {
    setSelectedAlertId(alertId);
    setSar(null);
    setGenerating(true);
    setError(null);
    try {
      const result = await api.generateSar(alertId);
      setSar(result);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "SAR generation failed");
    } finally {
      setGenerating(false);
    }
  }

  return (
    <div className="dashboard">
      <header className="topbar">
        <h1>FinSight — Alert Queue</h1>
        <div className="topbar-right">
          <span className="role-badge">{role}</span>
          <button className="link-button" onClick={logout}>
            Sign out
          </button>
        </div>
      </header>

      {error && <div className="error-banner">{error}</div>}

      <div className="layout">
        <section className="alert-list">
          <div className="section-header">
            <h2>Unresolved Alerts</h2>
            <button onClick={loadAlerts} disabled={loading}>
              {loading ? "Refreshing..." : "Refresh"}
            </button>
          </div>

          {alerts.length === 0 && !loading && <p className="empty">No unresolved alerts.</p>}

          <table>
            <thead>
              <tr>
                <th>Severity</th>
                <th>Rule</th>
                <th>Created</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {alerts.map((alert) => (
                <tr
                  key={alert.id}
                  className={selectedAlertId === alert.id ? "selected" : ""}
                >
                  <td>
                    <span className={`severity-badge severity-${alert.severity}`}>
                      {alert.severity}
                    </span>
                  </td>
                  <td>{alert.rule_triggered ?? "—"}</td>
                  <td>{new Date(alert.created_at).toLocaleString()}</td>
                  <td>
                    <button
                      onClick={() => handleGenerateSar(alert.id)}
                      disabled={generating && selectedAlertId === alert.id}
                    >
                      {generating && selectedAlertId === alert.id
                        ? "Generating..."
                        : "Generate SAR"}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>

        <section className="sar-panel">
          <h2>SAR Report</h2>
          {!sar && !generating && <p className="empty">Select an alert and generate a SAR to review it here.</p>}
          {generating && <p className="empty">Drafting narrative and running LLM-as-Judge evaluation…</p>}

          {sar && (
            <div className="sar-detail">
              <div className="judge-card">
                <h3>LLM-as-Judge Verdict</h3>
                {sar.judge_score === null ? (
                  <p className="judge-unavailable">Judge evaluation unavailable for this report.</p>
                ) : (
                  <>
                    <div className={`judge-score ${sar.judge_passed ? "pass" : "fail"}`}>
                      {(sar.judge_score * 100).toFixed(0)}%{" "}
                      <span className="judge-status">{sar.judge_passed ? "PASS" : "NEEDS REVIEW"}</span>
                    </div>
                    <p className="judge-critique">{sar.judge_critique}</p>
                  </>
                )}
              </div>

              <h3>Narrative</h3>
              <pre className="narrative">{sar.narrative}</pre>

              {sar.pdf_path && (
                <a
                  className="download-link"
                  href={api.pdfDownloadUrl(sar.id)}
                  target="_blank"
                  rel="noreferrer"
                >
                  Download PDF
                </a>
              )}
            </div>
          )}
        </section>
      </div>
    </div>
  );
}
