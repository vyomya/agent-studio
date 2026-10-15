# Agent Studio Architecture

## Overview
Agent Studio is a web service that converts a short textual specification into a self‑contained HTML page. The system is organized into four layers:

1. **Front‑end (Spec UI)** – FastAPI renders a page with a spec textbox, optional style example, and a *Generate* button. Input is validated (non‑empty, ≤ 500 chars) before any model call.
2. **Generator** – Calls a configurable LLM provider (primary and fallback URLs from env) to produce a single HTML document with inline CSS. A `mock` provider is used in tests and can be instructed to return valid or malformed pages.
3. **Validator & Retry** – Pure Python code parses the HTML, checks required elements (title, one <h1>, ≥ 3 <section>, size ≤ 100 KB, no `<script>`/event handlers/external resources/iframes), and returns a list of human‑readable errors. On failure the errors are fed back to the generator for up to three attempts.
4. **Persistence & Gallery** – Valid pages are stored in PostgreSQL (spec, HTML, attempt count, timestamps, version chain). The gallery lists pages newest‑first, rendering each inside an `iframe sandbox srcdoc="…"` with the most restrictive sandbox flags. A *Refine* workflow creates a new version while keeping prior versions immutable.

### Supporting Services
- **Caddy** terminates HTTPS on `<ip‑with‑dashes>.sslip.io` and proxies to the FastAPI app. The app, PostgreSQL 16, and Caddy services, configuration mounts, ports, and persistent volumes are defined in [`deploy/docker-compose.yml`](../deploy/docker-compose.yml).
- **PostgreSQL** runs via Docker Compose; schema includes a `pages` table with columns for `id`, `spec`, `html`, `attempts`, `created_at`, `parent_id`, `version`.
- **Rate Limiting** – per‑visitor limits (5/hour, 20/day) and a configurable global daily cap are enforced before any model call.
- **Deployment** – `deploy/install.sh` installs Docker, starts Compose, applies migrations, and ensures the service restarts on VM reboot. The script is idempotent.

### Data Flow
```
User Spec → Front‑end validation → Generator → Validator
        ↘︎ success → Save to DB → Gallery (iframe sandbox)
        ↘︎ failure → Retry (max 3) → final error message
```

The architecture isolates untrusted HTML to a sandboxed iframe, guaranteeing that invalid pages are never served as top‑level content. Limits protect the model allowance and keep the system within budget.
