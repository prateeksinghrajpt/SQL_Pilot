import { useEffect, useState } from "react";

type HealthResponse = { status: string; service: string; version: string };
const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

export default function App() {
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [apiError, setApiError] = useState<string | null>(null);
  const [question, setQuestion] = useState("");

  useEffect(() => {
    const controller = new AbortController();
    fetch(`${API_BASE_URL}/api/v1/health`, { signal: controller.signal })
      .then(async (response) => {
        if (!response.ok) throw new Error(`API returned HTTP ${response.status}`);
        return (await response.json()) as HealthResponse;
      })
      .then(setHealth)
      .catch((error: unknown) => {
        if (error instanceof Error && error.name === "AbortError") return;
        setApiError(error instanceof Error ? error.message : "Could not reach the API");
      });
    return () => controller.abort();
  }, []);

  function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    // Intentionally no generation API call in Phase 1.
  }

  const examples = [
    "Which customers have placed orders?",
    "What are our most expensive products?",
    "Show orders by status"
  ];

  return (
    <main className="app-shell">
      <aside className="sidebar">
        <div className="brand-mark">S</div>
        <div className="brand-copy"><strong>SQL Copilot</strong><span>AI data workspace</span></div>
        <div className="sidebar-section">WORKSPACE</div>
        <button className="nav-item active" type="button"><span>⌘</span> New query</button>
        <button className="nav-item" type="button" disabled title="Available in a later phase"><span>◷</span> Query history</button>
        <button className="nav-item" type="button" disabled title="Available in a later phase"><span>▤</span> Schema explorer</button>
        <div className="sidebar-bottom">
          <span className={`status-dot ${health ? "online" : apiError ? "offline" : ""}`} />
          <div>
            <strong>{health ? "API connected" : apiError ? "API unavailable" : "Connecting…"}</strong>
            <span>{health ? `v${health.version}` : apiError ?? "Checking backend"}</span>
          </div>
        </div>
      </aside>
      <section className="main-panel">
        <header className="topbar">
          <div><span className="eyebrow">YOUR DATA, IN PLAIN ENGLISH</span><h1>Ask your data</h1></div>
          <span className="phase-tag">PHASE 1 · FOUNDATION</span>
        </header>
        <div className="content">
          <div className="welcome-icon" aria-hidden="true">✳</div>
          <h2>What would you like to know?</h2>
          <p className="subtitle">Describe a business question. SQL generation will be enabled in a later phase.</p>
          <form className="query-box" onSubmit={handleSubmit}>
            <label className="sr-only" htmlFor="question">Your data question</label>
            <textarea id="question" value={question} onChange={(event) => setQuestion(event.target.value)}
              placeholder="e.g. Show the top 10 customers by total revenue…" rows={3} />
            <div className="query-box-footer">
              <span className="input-hint">Natural language → SQL (coming soon)</span>
              <button className="submit-button" type="submit" disabled={!question.trim()}>Prepare question <span>↗</span></button>
            </div>
          </form>
          <div className="section-label">TRY ASKING</div>
          <div className="suggestions">
            {examples.map((example) => (
              <button className="suggestion" type="button" key={example} onClick={() => setQuestion(example)}>
                <span>↗</span> {example}
              </button>
            ))}
          </div>
          <div className="notice"><span>ⓘ</span><p><strong>Foundation build.</strong> This interface currently checks backend connectivity. It does not yet generate or execute SQL.</p></div>
        </div>
        <footer className="footer"><span>Built with FastAPI · React · PostgreSQL</span><a href={`${API_BASE_URL}/docs`} target="_blank" rel="noreferrer">API documentation ↗</a></footer>
      </section>
    </main>
  );
}
