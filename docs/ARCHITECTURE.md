# Agent Studio Architecture Overview

## Core Components
- **Spec Processor** – Parses the high‑level `PLAN.md` spec and produces structured task definitions.
- **Validator** – Checks generated HTML/CSS/JS against a whitelist of allowed tags, attribute safety, and model‑usage limits.
- **Generator** – Calls the LLM (via Hermes) to produce page fragments, images, and metadata according to the spec. It respects per‑request token caps and model allowance limits.
- **Retry Loop** – Wraps Generator + Validator calls, retries on transient failures (network, timeout, validation errors) up to a configurable max.
- **Database** – PostgreSQL tables (`pages`, `galleries`, `metrics`) store generated content, versioning info, and audit logs.
- **Web Server** – FastAPI app serves the public endpoint (`https://<app>.sslip.io`). All generated HTML is sandboxed in an iframe with CSP headers; no inline scripts are allowed.
- **Gallery UI** – Renders a searchable gallery of saved pages, showing thumbnails, version history, and download options.

## Data Flow
1. **Spec → Task** – `PLAN.md` → `Task` objects (core tickets).
2. **Task → Generator Prompt** – Prompt includes validator rules and model‑allowance limits.
3. **Generator → Raw HTML** – LLM output.
4. **Validator → Clean HTML** – Strips disallowed elements, enforces CSP, returns safe HTML.
5. **Retry Loop** – On validation failure, regenerates with adjusted prompt.
6. **Database Store** – Approved HTML stored with version number; gallery metadata updated.
7. **Web Server** – Serves stored pages; gallery UI queries DB for listings.

## Safety & Limits
- **Model Allowance** – Configurable daily token quota per model; enforced in Generator.
- **Validation Rules** – Whitelist of tags (`<p>`, `<h1‑h6>`, `<ul>`, `<ol>`, `<img>`, `<a>`), safe attributes, no scripts/styles that could execute.
- **CSP Isolation** – `Content‑Security‑Policy: sandbox allow‑same‑origin;` ensures generated content cannot affect the host.
- **Retry Policy** – Max 3 attempts per page, exponential back‑off, logs failures for review.
- **Audit Log** – Every generation, validation, and retry round logs input prompt, output, and timestamps.

## Deployment Skeleton (Ticket #14)
- FastAPI app with a single `/` endpoint returning a health check JSON.
- Dockerfile builds the app; Docker Compose defines the service, PostgreSQL, and a sidecar for retries.
- CI pipeline runs unit tests, linting, and verifies that the skeleton launches on the public URL.

## Ticket Dependencies (example)
- `#14 Thin deployable skeleton` → none.
- `#6 Save pages and gallery` → depends on #14.
- `#5 Retry loop` → depends on #6.
- `#4 HTML validator` → depends on #5.
- `#3 Generator configuration` → depends on #4.
- `#2 Spec page UI` → depends on #3.
- `#1 Core spec processor` → depends on #2.
- `#7 Model allowance limits` → independent, but used by Generator.
- `#8 Refine pages with versions` → depends on #6.
- `#9 Deploy and install script` → depends on #14.

These tickets will be created below, each labeled with `type:feature` and the appropriate `area:` label. All tickets are handed to the lead (`agent:lead`).
