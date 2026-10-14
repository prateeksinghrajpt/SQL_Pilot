# SQL Copilot

A private, file-based SQL workspace. Each user creates named projects, uploads schema and data files, and asks questions about the imported dataset. The LLM uses the project schema to generate DuckDB SQL; the query executes only against that project's local DuckDB file.

## Run locally

Requirements: Docker Desktop, Python 3.12+, and Node.js 20+.

```powershell
Copy-Item .env.example .env
docker compose up --build
```

Open http://localhost:5173, register an account, choose **Import schema and data**, name the project, and upload one or more files. No database connection URL or database server is required.

`OPENAI_API_KEY` is needed for natural-language SQL generation and for extraction from documents/images. CSV, JSON, and Excel files are parsed directly. PDF, DOCX, TXT, Markdown, and supported image files use the LLM to extract a structured schema and rows; those requests incur model usage. Imported projects and the account database persist in the `app_data` Docker volume.

## Supported imports

- `.csv`: one table per file, with the first row as column names.
- `.json`: a row-object array, an object containing rows, a name-to-row-list map, or a `{ "tables": [...] }` schema/data structure.
- `.xlsx`: one table per worksheet, with the first row as column names.
- `.pdf`, `.docx`, `.txt`, `.md`, `.png`, `.jpg`, `.jpeg`, `.webp`: schema and tabular data extracted as structured JSON by the configured model.

Uploads are limited to 10 files, 20 MB per file, and 50 MB total. Review AI-extracted data before relying on it; unclear values may be omitted or interpreted incorrectly.

## Tests and build

```powershell
cd backend
..\venv\Scripts\python.exe -m pytest -q
cd ..\frontend
npm run build
cd ..
docker compose config --quiet
```

Tests use temporary control-plane databases and per-project DuckDB files; no external database is required.

## Isolation and execution

- Authentication uses salted Argon2id password hashes, HttpOnly session cookies, and CSRF validation on state-changing requests.
- Projects are private to their owner. Project IDs are checked against the current user before schema, data, or SQL operations.
- Uploaded files are parsed and stored in a dedicated DuckDB file for each project. The source files’ contents are not sent to an LLM for CSV/JSON/Excel imports; document and image imports require LLM extraction.
- DuckDB external file/network access is disabled for project query connections. SQL is parsed as one statement and limited to `SELECT`, `INSERT`, `UPDATE`, and `DELETE`; `UPDATE` and `DELETE` require a `WHERE` clause.
- Mutations are disabled per project by default. Enabling them requires a project setting and explicit run acknowledgement.
- `SELECT` uses a read-only DuckDB connection, and responses are capped by `MAX_RESULT_ROWS`.

This is a portfolio/demo implementation. Treat uploaded data as sensitive: local control-plane and DuckDB files are stored unencrypted on disk. Before exposing the app to untrusted users, add encrypted-at-rest dataset storage, upload malware scanning, rate limits, audit logging, retention controls, and operational monitoring. Use HTTPS and set `COOKIE_SECURE=true` in production.

## Configuration

- `OPENAI_API_KEY`: required for SQL generation and extraction from documents/images.
- `OPENAI_MODEL`: model name; defaults to `gpt-4o-mini`.
- `APP_DATABASE_PATH`: SQLite account/project metadata file; Docker Compose stores it under the persistent `app_data` volume.
- `MAX_RESULT_ROWS`: maximum returned rows; defaults to 200.
- `COOKIE_SECURE`: set to `true` when served over HTTPS.

`docker compose down -v` deletes the local account/project metadata and all imported project datasets.
