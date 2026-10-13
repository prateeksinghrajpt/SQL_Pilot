import { useEffect, useState } from "react";

type HealthResponse = { status: string; service: string; version: string };
const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

const SQL_KEYWORDS = new Set([
  "SELECT","FROM","WHERE","JOIN","LEFT","RIGHT","INNER","OUTER","ON","AS","AND","OR","IN","LIKE","IS","NULL","DISTINCT","COUNT","SUM","AVG","MAX","MIN","GROUP","BY","ORDER","LIMIT","HAVING","CASE","WHEN","THEN","ELSE","END","INSERT","INTO","VALUES","UPDATE","DELETE","CREATE","TABLE","ALTER","DROP","WITH","UNION","ALL","NOT","EXISTS","BETWEEN","DESC","ASC"
]);

function renderSqlTokens(sql: string) {
  const tokenRegex = /(\s+|--.*?$|'.*?'|".*?"|`.*?`|\b(?:SELECT|FROM|WHERE|JOIN|LEFT|RIGHT|INNER|OUTER|ON|AS|AND|OR|IN|LIKE|IS|NULL|DISTINCT|COUNT|SUM|AVG|MAX|MIN|GROUP|BY|ORDER|LIMIT|HAVING|CASE|WHEN|THEN|ELSE|END|INSERT|INTO|VALUES|UPDATE|DELETE|CREATE|TABLE|ALTER|DROP|WITH|UNION|ALL|NOT|EXISTS|BETWEEN|DESC|ASC)\b|\b[A-Za-z_][A-Za-z0-9_]*\b|\d+(?:\.\d+)?|[(),.;=<>+\-*\/]+)/gim;

  const parts: { text: string; className?: string }[] = [];
  let lastIndex = 0;

  for (const match of sql.matchAll(tokenRegex)) {
    const value = match[0];
    const index = match.index ?? 0;

    if (index > lastIndex) {
      parts.push({ text: sql.slice(lastIndex, index) });
    }

    const upper = value.toUpperCase();
    let className: string | undefined;

    if (/^\s+$/.test(value)) {
      className = undefined;
    } else if (/^['"`]/.test(value)) {
      className = "sql-token-string";
    } else if (/^\d+(?:\.\d+)?$/.test(value)) {
      className = "sql-token-number";
    } else if (SQL_KEYWORDS.has(upper)) {
      className = "sql-token-keyword";
    } else if (/^[(),.;=<>+\-*\/]+$/.test(value)) {
      className = "sql-token-punctuation";
    } else {
      className = "sql-token-identifier";
    }

    parts.push({ text: value, className });
    lastIndex = index + value.length;
  }

  if (lastIndex < sql.length) {
    parts.push({ text: sql.slice(lastIndex) });
  }

  return parts.map((part, index) => (
    <span key={`${part.text}-${index}`} className={part.className}>{part.text}</span>
  ));
}

export default function App() {
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [apiError, setApiError] = useState<string | null>(null);
  const [question, setQuestion] = useState("");
  const [generatedSql, setGeneratedSql] = useState("");
  const [queryResult, setQueryResult] = useState<Record<string, unknown>[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [runningSql, setRunningSql] = useState(false);
  const [isEditingSql, setIsEditingSql] = useState(false);
  const [error, setError] = useState<string | null>(null);

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

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setQueryResult(null);
    setGeneratedSql("");
    setLoading(true);

    try {
      const response = await fetch(`${API_BASE_URL}/api/v1/sql/generate`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question }),
      });

      if (!response.ok) {
        const body = await response.json().catch(() => ({}));
        throw new Error(body.detail ?? "Could not generate SQL");
      }

      const data = await response.json() as { sql: string };
      setGeneratedSql(data.sql);
    } catch (requestError: unknown) {
      setError(requestError instanceof Error ? requestError.message : "Unknown error");
    } finally {
      setLoading(false);
    }
  }

  async function handleRunSql() {
    if (!generatedSql.trim()) return;

    setError(null);
    setRunningSql(true);
    setQueryResult(null);

    try {
      const response = await fetch(`${API_BASE_URL}/api/v1/sql/run`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ sql: generatedSql }),
      });

      if (!response.ok) {
        const body = await response.json().catch(() => ({}));
        throw new Error(body.detail ?? "Could not execute SQL");
      }

      const result = await response.json() as { rows: Record<string, unknown>[]; columns: string[] };
      setQueryResult(result.rows);
    } catch (requestError: unknown) {
      setError(requestError instanceof Error ? requestError.message : "Unknown error");
    } finally {
      setRunningSql(false);
    }
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
          <p className="subtitle">Describe a business question. The app will generate SQL for review, then you can edit and run it manually.</p>
          <form className="query-box" onSubmit={handleSubmit}>
            <label className="sr-only" htmlFor="question">Your data question</label>
            <textarea id="question" value={question} onChange={(event) => setQuestion(event.target.value)}
              placeholder="e.g. Show the top 10 customers by total revenue…" rows={3} />
            <div className="query-box-footer">
              <span className="input-hint">Natural language → SQL draft</span>
              <button className="submit-button" type="submit" disabled={!question.trim() || loading}>{loading ? "Generating…" : "Prepare question"} <span>↗</span></button>
            </div>
          </form>
          {error && <div className="notice error"><span>⚠</span><p>{error}</p></div>}
          <div className="sql-editor-shell">
            <div className="sql-editor-header">
              <div className="sql-editor-brand">
                <span className="editor-icon">&lt;/&gt;</span>
                <span className="sql-editor-label">SQL</span>
              </div>
              <div className="sql-editor-actions">
                <button
                  className="icon-button"
                  type="button"
                  onClick={() => setIsEditingSql((value) => !value)}
                  aria-label="Edit SQL"
                  disabled={!generatedSql.trim()}
                >
                  ✎
                </button>
                <button
                  className="icon-button"
                  type="button"
                  onClick={handleRunSql}
                  disabled={runningSql || !generatedSql.trim()}
                  aria-label="Run SQL"
                >
                  ▶
                </button>
              </div>
            </div>
            {generatedSql ? (
              isEditingSql ? (
                <textarea className="sql-editor" value={generatedSql} onChange={(event) => setGeneratedSql(event.target.value)} rows={10} />
              ) : (
                <pre className="sql-preview">{renderSqlTokens(generatedSql)}</pre>
              )
            ) : (
              <div className="sql-placeholder">SQL draft will appear here</div>
            )}
          </div>
          {queryResult && (
            <div className="notice results-box">
              <span>Results</span>
              <pre>{JSON.stringify(queryResult, null, 2)}</pre>
            </div>
          )}
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
