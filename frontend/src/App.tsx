import { useEffect, useState } from "react";

type HealthResponse = { status: string; service: string; version: string };
type User = {
  id: string;
  email: string;
  is_admin?: boolean;
  approval_status?: "trial" | "approved" | "pending" | "rejected";
  free_queries_used?: number;
  access_requested?: boolean;
};
type Project = {
  id: string;
  name: string;
  schema: { name: string; columns: { name: string; type?: string; is_primary_key?: boolean }[] }[];
  imported_at: string;
  allow_mutations: boolean;
  source_files: string[];
  row_count: number;
  created_at: string;
};
type AccessRequest = {
  id: string;
  email: string;
  approval_status: "trial" | "approved" | "pending" | "rejected";
  free_queries_used: number;
  access_requested_at: string | null;
  created_at: string;
};
const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

function csrfToken() {
  const cookie = document.cookie.split("; ").find((item) => item.startsWith("sql_copilot_csrf="));
  return cookie ? decodeURIComponent(cookie.split("=").slice(1).join("=")) : "";
}

function apiRequest(path: string, options: RequestInit = {}) {
  const headers = new Headers(options.headers);
  const method = (options.method ?? "GET").toUpperCase();
  const token = csrfToken();
  if (!(["GET", "HEAD", "OPTIONS"].includes(method)) && token) {
    headers.set("X-CSRF-Token", token);
  }
  return fetch(`${API_BASE_URL}${path}`, { ...options, headers, credentials: "include" });
}

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
  const [user, setUser] = useState<User | null>(null);
  const [authReady, setAuthReady] = useState(false);
  const [authMode, setAuthMode] = useState<"login" | "register">("login");
  const [authEmail, setAuthEmail] = useState("");
  const [authPassword, setAuthPassword] = useState("");
  const [authError, setAuthError] = useState<string | null>(null);
  const [projects, setProjects] = useState<Project[]>([]);
  const [activeProjectId, setActiveProjectId] = useState("");
  const [projectName, setProjectName] = useState("");
  const [importFiles, setImportFiles] = useState<File[]>([]);
  const [projectError, setProjectError] = useState<string | null>(null);
  const [projectBusy, setProjectBusy] = useState(false);
  const [showProjectForm, setShowProjectForm] = useState(false);
  const [question, setQuestion] = useState("");
  const [generatedSql, setGeneratedSql] = useState("");
  const [queryResult, setQueryResult] = useState<Record<string, unknown>[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [runningSql, setRunningSql] = useState(false);
  const [isEditingSql, setIsEditingSql] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [accessRequestMessage, setAccessRequestMessage] = useState<string | null>(null);
  const [showAccessRequests, setShowAccessRequests] = useState(false);
  const [adminRequests, setAdminRequests] = useState<AccessRequest[]>([]);
  const [adminError, setAdminError] = useState<string | null>(null);
  const [adminBusyId, setAdminBusyId] = useState<string | null>(null);
  const activeProject = projects.find((project) => project.id === activeProjectId) ?? null;
  const freeQueryUsed = user?.approval_status === "trial" && (user.free_queries_used ?? 0) >= 1;

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

  useEffect(() => {
    let cancelled = false;
    apiRequest("/api/v1/auth/me")
      .then(async (response) => {
        if (!response.ok) return null;
        return (await response.json() as { user: User }).user;
      })
      .then((currentUser) => {
        if (!cancelled) setUser(currentUser);
      })
      .catch(() => {
        if (!cancelled) setUser(null);
      })
      .finally(() => {
        if (!cancelled) setAuthReady(true);
      });
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    if (!user) {
      setProjects([]);
      setActiveProjectId("");
      return;
    }
    let cancelled = false;
    apiRequest("/api/v1/projects")
      .then(async (response) => {
        const body = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(body.detail ?? "Could not load projects");
        return body.projects as Project[];
      })
      .then((loadedProjects) => {
        if (cancelled) return;
        setProjects(loadedProjects);
        setActiveProjectId((current) => loadedProjects.some((project) => project.id === current)
          ? current
          : loadedProjects[0]?.id ?? "");
      })
      .catch((requestError: unknown) => {
        if (!cancelled) setProjectError(requestError instanceof Error ? requestError.message : "Could not load projects");
      });
    return () => { cancelled = true; };
  }, [user]);

  async function handleAuthSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setAuthError(null);
    try {
      const response = await apiRequest(`/api/v1/auth/${authMode === "register" ? "register" : "login"}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email: authEmail, password: authPassword }),
      });
      const body = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(body.detail ?? "Authentication failed");
      setUser(body.user as User);
      setAuthPassword("");
    } catch (requestError: unknown) {
      setAuthError(requestError instanceof Error ? requestError.message : "Authentication failed");
    }
  }

  async function handleLogout() {
    await apiRequest("/api/v1/auth/logout", { method: "POST" });
    setUser(null);
    setProjects([]);
    setActiveProjectId("");
    setGeneratedSql("");
    setQueryResult(null);
    setShowAccessRequests(false);
    setAdminRequests([]);
  }

  async function handleCreateProject(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setProjectError(null);
    setProjectBusy(true);
    try {
      const formData = new FormData();
      formData.set("name", projectName);
      importFiles.forEach((file) => formData.append("files", file));
      const response = await apiRequest("/api/v1/projects", {
        method: "POST",
        body: formData,
      });
      const body = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(body.detail ?? "Could not import database schema");
      const createdProject = body.project as Project;
      setProjects((current) => [createdProject, ...current]);
      setActiveProjectId(createdProject.id);
      setProjectName("");
      setImportFiles([]);
      setShowProjectForm(false);
      setGeneratedSql("");
      setQueryResult(null);
    } catch (requestError: unknown) {
      setProjectError(requestError instanceof Error ? requestError.message : "Could not create project");
    } finally {
      setProjectBusy(false);
    }
  }

  async function handleRefreshSchema() {
    if (!activeProject) return;
    setProjectBusy(true);
    setProjectError(null);
    try {
      const response = await apiRequest(`/api/v1/projects/${activeProject.id}/refresh-schema`, { method: "POST" });
      const body = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(body.detail ?? "Could not refresh schema");
      const refreshed = body.project as Project;
      setProjects((current) => current.map((project) => project.id === refreshed.id ? refreshed : project));
    } catch (requestError: unknown) {
      setProjectError(requestError instanceof Error ? requestError.message : "Could not refresh schema");
    } finally {
      setProjectBusy(false);
    }
  }

  async function handleRenameProject() {
    if (!activeProject) return;
    const name = window.prompt("Project name", activeProject.name)?.trim();
    if (!name || name === activeProject.name) return;
    await updateProject({ name });
  }

  async function updateProject(change: { name?: string; allow_mutations?: boolean }) {
    if (!activeProject) return;
    setProjectError(null);
    try {
      const response = await apiRequest(`/api/v1/projects/${activeProject.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(change),
      });
      const body = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(body.detail ?? "Could not update project");
      const updated = body.project as Project;
      setProjects((current) => current.map((project) => project.id === updated.id ? updated : project));
    } catch (requestError: unknown) {
      setProjectError(requestError instanceof Error ? requestError.message : "Could not update project");
    }
  }

  async function handleDeleteProject() {
    if (!activeProject || !window.confirm(`Delete project '${activeProject.name}'?`)) return;
    const response = await apiRequest(`/api/v1/projects/${activeProject.id}`, { method: "DELETE" });
    if (!response.ok) {
      setProjectError("Could not delete project");
      return;
    }
    setProjects((current) => current.filter((project) => project.id !== activeProject.id));
    setActiveProjectId("");
    setGeneratedSql("");
    setQueryResult(null);
  }

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!activeProject) return;
    setError(null);
    setAccessRequestMessage(null);
    setQueryResult(null);
    setGeneratedSql("");
    setLoading(true);

    try {
      const response = await apiRequest("/api/v1/sql/generate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ project_id: activeProject.id, question }),
      });

      if (!response.ok) {
        const body = await response.json().catch(() => ({}));
        throw new Error(body.detail ?? "Could not generate SQL");
      }

      const data = await response.json() as { sql: string };
      setGeneratedSql(data.sql);
      setUser((current) => current?.approval_status === "trial"
        ? { ...current, free_queries_used: (current.free_queries_used ?? 0) + 1 }
        : current);
    } catch (requestError: unknown) {
      setError(requestError instanceof Error ? requestError.message : "Unknown error");
    } finally {
      setLoading(false);
    }
  }

  async function handleRequestAccess() {
    setAccessRequestMessage(null);
    setError(null);
    try {
      const response = await apiRequest("/api/v1/auth/request-access", { method: "POST" });
      const body = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(body.detail ?? "Could not request access");
      setAccessRequestMessage(body.message ?? "Your access request was sent to Prateek Singh.");
      setUser((current) => current ? { ...current, access_requested: true } : current);
    } catch (requestError: unknown) {
      setError(requestError instanceof Error ? requestError.message : "Could not request access");
    }
  }

  async function loadAccessRequests() {
    if (!user?.is_admin) return;
    setAdminError(null);
    try {
      const response = await apiRequest("/api/v1/auth/admin/access-requests");
      const body = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(body.detail ?? "Could not load access requests");
      setAdminRequests(body.requests ?? []);
    } catch (requestError: unknown) {
      setAdminError(requestError instanceof Error ? requestError.message : "Could not load access requests");
    }
  }

  async function handleAccessDecision(requestUserId: string, approved: boolean) {
    setAdminBusyId(requestUserId);
    setAdminError(null);
    try {
      const response = await apiRequest(`/api/v1/auth/admin/access-requests/${requestUserId}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ approved }),
      });
      const body = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(body.detail ?? "Could not update access request");
      const updated = body.request as AccessRequest;
      setAdminRequests((current) => current.map((item) => item.id === updated.id ? updated : item));
    } catch (requestError: unknown) {
      setAdminError(requestError instanceof Error ? requestError.message : "Could not update access request");
    } finally {
      setAdminBusyId(null);
    }
  }

  function isMutationSql(sql: string) {
    return /^\s*(INSERT|UPDATE|DELETE|MERGE)\b/i.test(sql.trim());
  }

  async function handleRunSql() {
    if (!generatedSql.trim() || !activeProject) return;

    if (isMutationSql(generatedSql)) {
      const confirmed = window.confirm(
        `This SQL will modify data in '${activeProject.name}'. Do you want to continue?`
      );
      if (!confirmed) {
        return;
      }
    }

    setError(null);
    setRunningSql(true);
    setQueryResult(null);

    try {
      const response = await apiRequest("/api/v1/sql/run", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          project_id: activeProject.id,
          sql: generatedSql,
          acknowledge_mutation: isMutationSql(generatedSql),
        }),
      });

      const result = await response.json().catch(() => ({}));

      if (!response.ok) {
        throw new Error(result.detail ?? "Could not execute SQL");
      }

      setQueryResult(result.rows ?? []);
    } catch (requestError: unknown) {
      setError(requestError instanceof Error ? requestError.message : "Unknown error");
    } finally {
      setRunningSql(false);
    }
  }

  const firstTable = activeProject?.schema[0];
  const examples = firstTable ? [
    `Show the first 10 rows from ${firstTable.name}`,
    `Count records in ${firstTable.name}`,
    `List ${firstTable.name} with its primary key`,
  ] : [];

  if (!authReady) {
    return <main className="auth-screen"><div className="auth-panel">Checking session…</div></main>;
  }

  if (!user) {
    return (
      <main className="auth-screen">
        <section className="auth-panel">
          <div className="brand-mark">S</div>
          <p className="eyebrow">PRIVATE SQL WORKSPACE</p>
          <h1>{authMode === "register" ? "Create your account" : "Sign in to SQL Copilot"}</h1>
          <p className="subtitle">Your database projects and schema context stay separated by account.</p>
          <form className="auth-form" onSubmit={handleAuthSubmit}>
            <label htmlFor="auth-email">Email</label>
            <input id="auth-email" type="email" autoComplete="email" required value={authEmail} onChange={(event) => setAuthEmail(event.target.value)} />
            <label htmlFor="auth-password">Password</label>
            <input id="auth-password" type="password" autoComplete={authMode === "register" ? "new-password" : "current-password"} minLength={12} required value={authPassword} onChange={(event) => setAuthPassword(event.target.value)} />
            {authError && <div className="notice error"><span>⚠</span><p>{authError}</p></div>}
            <button className="submit-button" type="submit">{authMode === "register" ? "Create account" : "Sign in"}</button>
          </form>
          <button className="auth-switch" type="button" onClick={() => { setAuthError(null); setAuthMode((mode) => mode === "login" ? "register" : "login"); }}>
            {authMode === "register" ? "Already registered? Sign in" : "New here? Create an account"}
          </button>
        </section>
      </main>
    );
  }

  return (
    <main className="app-shell">
      <aside className="sidebar">
        <div className="brand-mark">S</div>
        <div className="brand-copy"><strong>SQL Copilot</strong><span>AI data workspace</span></div>
        <div className="sidebar-section">WORKSPACE</div>
        <button className="nav-item active" type="button" onClick={() => { setGeneratedSql(""); setQueryResult(null); setQuestion(""); setError(null); setAccessRequestMessage(null); }}><span>⌘</span> New query</button>
        {user.is_admin && (
          <button className={`nav-item ${showAccessRequests ? "active" : ""}`} type="button" onClick={() => {
            setShowAccessRequests((shown) => {
              if (!shown) void loadAccessRequests();
              return !shown;
            });
          }}>
            <span>!</span> Access requests
          </button>
        )}
        <div className="project-controls">
          <label className="sidebar-section" htmlFor="active-project">PROJECT</label>
          <select id="active-project" value={activeProjectId} onChange={(event) => {
            setShowAccessRequests(false);
            setActiveProjectId(event.target.value);
            setGeneratedSql("");
            setQueryResult(null);
            setError(null);
            setAccessRequestMessage(null);
          }}>
            <option value="">Select a project</option>
            {projects.map((project) => <option value={project.id} key={project.id}>{project.name}</option>)}
          </select>
          <button className="project-action" type="button" onClick={() => setShowProjectForm((shown) => !shown)}>
            {showProjectForm ? "Close import" : "+ Import database"}
          </button>
          {showProjectForm && (
            <form className="project-form" onSubmit={handleCreateProject}>
              <label htmlFor="project-name">Project name</label>
              <input id="project-name" value={projectName} onChange={(event) => setProjectName(event.target.value)} placeholder="Project 1" required maxLength={80} />
              <label htmlFor="project-files">Schema and data files</label>
              <input id="project-files" type="file" multiple accept=".csv,.json,.xlsx,.txt,.md,.pdf,.docx,.png,.jpg,.jpeg,.webp" onChange={(event) => setImportFiles(Array.from(event.target.files ?? []))} required />
              <span className="project-upload-hint">CSV, JSON, and Excel stay local. Documents and images are sent to your configured model for extraction.</span>
              <button className="submit-button" type="submit" disabled={projectBusy || !projectName.trim() || importFiles.length === 0}>{projectBusy ? "Importing schema and data…" : `Import ${importFiles.length || "files"}`}</button>
            </form>
          )}
          {projectError && <div className="project-error">{projectError}</div>}
          {activeProject && (
            <div className="project-details">
              <div className="project-details-header">
                <strong>SCHEMA</strong>
                <button className="project-action" type="button" onClick={handleRefreshSchema} disabled={projectBusy} aria-label="Refresh project schema" title="Refresh schema">↻</button>
              </div>
              <span className="schema-refresh-time">Imported {new Date(activeProject.imported_at).toLocaleString()}</span>
              <span className="schema-refresh-time">{activeProject.source_files.join(", ")}</span>
              <span className="schema-refresh-time">{activeProject.row_count.toLocaleString()} imported rows</span>
              {activeProject.schema.map((table) => (
                <details className="project-table" key={table.name}>
                  <summary>{table.name}</summary>
                  {table.columns.map((column) => <span className="project-column" key={column.name}>{column.name}<small>{column.type}{column.is_primary_key ? " · PK" : ""}</small></span>)}
                </details>
              ))}
              <label className="mutation-setting"><input type="checkbox" checked={activeProject.allow_mutations} onChange={(event) => {
                if (event.target.checked && !window.confirm("Allow INSERT, UPDATE, and DELETE queries for this project?")) return;
                void updateProject({ allow_mutations: event.target.checked });
              }} /> Allow data changes</label>
              <div className="project-actions-row">
                <button className="project-action" type="button" onClick={handleRenameProject}>Rename</button>
                <button className="project-action danger" type="button" onClick={handleDeleteProject}>Delete</button>
              </div>
            </div>
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
          <div><span className="eyebrow">{activeProject ? `PROJECT · ${activeProject.name}` : "YOUR DATA, IN PLAIN ENGLISH"}</span><h1>{activeProject ? "Ask this database" : "Your projects"}</h1></div>
          <div className="account-actions"><span>{user.email}</span><button className="project-action" type="button" onClick={handleLogout}>Sign out</button></div>
        </header>
        <div className="content">
          <div className="workspace-shell">
            <div className="workspace-main">
              {showAccessRequests ? (
                <div className="admin-panel">
                  <div className="section-label">PENDING ACCESS</div>
                  {adminError && <div className="notice error"><span>!</span><p>{adminError}</p></div>}
                  {adminRequests.length === 0 ? (
                    <div className="results-empty">No access requests yet.</div>
                  ) : (
                    <div className="admin-request-list">
                      {adminRequests.map((request) => (
                        <div className="admin-request" key={request.id}>
                          <div>
                            <strong>{request.email}</strong>
                            <span>{request.approval_status} - {request.free_queries_used} free query used</span>
                            {request.access_requested_at && <span>Requested {new Date(request.access_requested_at).toLocaleString()}</span>}
                          </div>
                          <div className="admin-request-actions">
                            <button className="project-action" type="button" disabled={adminBusyId === request.id || request.approval_status === "approved"} onClick={() => void handleAccessDecision(request.id, true)}>Approve</button>
                            <button className="project-action danger" type="button" disabled={adminBusyId === request.id || request.approval_status === "rejected"} onClick={() => void handleAccessDecision(request.id, false)}>Reject</button>
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              ) : activeProject ? <>
              <div className="welcome-icon" aria-hidden="true">✳</div>
              <h2>What would you like to know?</h2>
              <p className="subtitle">Describe a business question. The app will generate SQL for review, then you can edit and run it manually.</p>
              <form className="query-box" onSubmit={handleSubmit}>
                <label className="sr-only" htmlFor="question">Your data question</label>
                <textarea id="question" value={question} onChange={(event) => setQuestion(event.target.value)}
                  placeholder="e.g. Show the top 10 customers by total revenue…" rows={3} />
                <div className="query-box-footer">
                  <span className="input-hint">{freeQueryUsed ? "Free query used" : "Natural language → SQL draft"}</span>
                  <span title={freeQueryUsed ? "Please raise an access request to generate more SQL." : undefined}>
                    <button className="submit-button" type="submit" disabled={!question.trim() || loading || freeQueryUsed}>{loading ? "Generating…" : "Prepare question"} <span>↗</span></button>
                  </span>
                </div>
              </form>
              {error && <div className="notice error"><span>⚠</span><p>{error}</p></div>}
              {freeQueryUsed && (
                <div className="notice access-lock">
                  <span>!</span>
                  <p>{user.access_requested ? "Your access request has been sent to Prateek Singh." : "You have used your free query. Request access from Prateek Singh to generate more SQL."}</p>
                  {!user.access_requested && <button className="project-action" type="button" onClick={handleRequestAccess}>Request access</button>}
                </div>
              )}
              {accessRequestMessage && <div className="notice"><span>i</span><p>{accessRequestMessage}</p></div>}
              {generatedSql && isMutationSql(generatedSql) && (
                <div className="notice error">
                  <span>⚠</span>
                  <p><strong>Data-changing query:</strong> this statement will update or delete records and may affect existing data.</p>
                </div>
              )}
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
                      className="icon-button run-button"
                      type="button"
                      onClick={handleRunSql}
                      disabled={runningSql || !generatedSql.trim()}
                      aria-label={runningSql ? "Running SQL" : "Run SQL"}
                    >
                      {runningSql ? <span className="spinner" aria-hidden="true" /> : <span aria-hidden="true">▶</span>}
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
              {queryResult ? (
                <div className="results-box">
                  <div className="results-header">
                    <h3>Results</h3>
                    <span>[{queryResult.length}]</span>
                  </div>
                  <pre>{JSON.stringify(queryResult, null, 2)}</pre>
                </div>
              ) : (
                <div className="results-empty">Results will appear here.</div>
              )}
              <div className="section-label">TRY ASKING</div>
              <div className="suggestions">
                {examples.map((example) => (
                  <button className="suggestion" type="button" key={example} onClick={() => setQuestion(example)}>
                    <span>↗</span> {example}
                  </button>
                ))}
              </div>
              <div className="notice"><span>ⓘ</span><p>SQL generation and validation use the imported schema for {activeProject.name}.</p></div>
              </> : (
                <div className="project-empty">
                  <h2>Import a data project</h2>
                  <p>Upload schema and data files. SQL is generated from the imported schema and runs only against this project’s imported dataset.</p>
                  <button className="submit-button" type="button" onClick={() => setShowProjectForm(true)}>Import schema and data</button>
                </div>
              )}
            </div>

          </div>
        </div>
        <footer className="footer"><span>FastAPI · DuckDB · AI schema extraction</span><a href={`${API_BASE_URL}/docs`} target="_blank" rel="noreferrer">API documentation ↗</a></footer>
      </section>
    </main>
  );
}
