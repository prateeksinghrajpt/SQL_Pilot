import { useEffect, useMemo, useState } from "react";

type HealthResponse = { status: string; service: string; version: string };
type SchemaColumn = { name: string; type?: string; nullable?: boolean; is_primary_key?: boolean };
type SchemaForeignKey = { column: string; references_table: string; references_column: string };
type SchemaTable = {
  name: string;
  column_count: number;
  primary_key_count: number;
  foreign_key_count: number;
  columns: SchemaColumn[];
  primary_keys: string[];
  foreign_keys: SchemaForeignKey[];
};
type SchemaSummary = { table_count: number; tables: SchemaTable[] };
type QueryHistoryItem = { id: string; question: string; sql: string; createdAt: string };
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
  const [schemaSummary, setSchemaSummary] = useState<SchemaSummary | null>(null);
  const [queryHistory, setQueryHistory] = useState<QueryHistoryItem[]>(() => {
    if (typeof window === "undefined") return [];
    try {
      const raw = window.localStorage.getItem("sql-copilot-history");
      return raw ? (JSON.parse(raw) as QueryHistoryItem[]) : [];
    } catch {
      return [];
    }
  });

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

    fetch(`${API_BASE_URL}/api/v1/schema/summary`, { signal: controller.signal })
      .then(async (response) => {
        if (!response.ok) throw new Error(`Schema returned HTTP ${response.status}`);
        return (await response.json()) as SchemaSummary;
      })
      .then(setSchemaSummary)
      .catch((error: unknown) => {
        if (error instanceof Error && error.name === "AbortError") return;
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
      setQueryHistory((current) => {
        const next = [{
          id: `${Date.now()}`,
          question,
          sql: data.sql,
          createdAt: new Date().toISOString(),
        }, ...current].slice(0, 6);

        if (typeof window !== "undefined") {
          window.localStorage.setItem("sql-copilot-history", JSON.stringify(next));
        }

        return next;
      });
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

  function handleSchemaInsert(value: string) {
    setQuestion((current) => {
      const trimmed = current.trim();
      if (!trimmed) return value;
      return `${trimmed} ${value}`;
    });
  }

  const examples = useMemo(() => {
    if (!schemaSummary || schemaSummary.tables.length === 0) {
      return [
        "Which customers have placed orders?",
        "What are our most expensive products?",
        "Show orders by status",
      ];
    }

    const firstTable = schemaSummary.tables[0];
    const firstColumn = firstTable.columns[0]?.name ?? "id";

    return [
      `Show the first 10 rows from ${firstTable.name}`,
      `List ${firstTable.name} by ${firstColumn}`,
      `Which records in ${firstTable.name} have a primary key?`,
    ];
  }, [schemaSummary]);

  return (
    <main className="app-shell">
      <aside className="sidebar">
        <div className="brand-mark">S</div>
        <div className="brand-copy"><strong>SQL Copilot</strong><span>AI data workspace</span></div>
        <div className="sidebar-section">WORKSPACE</div>
        <button className="nav-item active" type="button"><span>⌘</span> New query</button>

        <div className="history-panel">
          <div className="sidebar-section">RECENT</div>
          {queryHistory.length === 0 ? (
            <div className="history-empty">No recent queries yet</div>
          ) : (
            queryHistory.map((item) => (
              <button
                key={item.id}
                type="button"
                className="history-item"
                onClick={() => {
                  setQuestion(item.question);
                  setGeneratedSql(item.sql);
                }}
              >
                <span className="history-item-title">{item.question}</span>
                <span className="history-item-meta">{new Date(item.createdAt).toLocaleDateString()}</span>
              </button>
            ))
          )}
        </div>

        <div className="schema-panel">
          <div className="sidebar-section">SCHEMA</div>
          {schemaSummary ? (
            schemaSummary.tables.slice(0, 6).map((table) => (
              <div className="schema-table" key={table.name}>
                <button type="button" className="schema-table-name schema-table-button" onClick={() => handleSchemaInsert(table.name)}>
                  {table.name}
                </button>
                <ul className="schema-columns">
                  {table.columns.slice(0, 4).map((column) => (
                    <li key={`${table.name}-${column.name}`}>
                      <button
                        type="button"
                        className="schema-column-button"
                        onClick={() => handleSchemaInsert(`${table.name}.${column.name}`)}
                      >
                        <span className="schema-column-name">{column.name}</span>
                        {column.is_primary_key && <span className="schema-tag">PK</span>}
                      </button>
                    </li>
                  ))}
                  {table.columns.length > 4 && (
                    <li className="schema-more">+{table.columns.length - 4} more</li>
                  )}
                </ul>
              </div>
            ))
          ) : (
            <div className="schema-empty">Loading schema…</div>
          )}
        </div>

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
