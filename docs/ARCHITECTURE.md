# Architecture Overview

## Components
- **Spec Processor**: Reads user specifications from the issue tracker, validates them, and triggers the generation pipeline.
- **Generator Core**: Runs the language model to produce HTML snippets, JSON metadata, and image prompts. Handles retries, token limits, and safety filters.
- **Validator**: Checks generated HTML for unsafe scripts, sanitizes, and ensures compliance with the content policy.
- **Database**: PostgreSQL table `generated_items(id SERIAL PRIMARY KEY, spec_id INT, html TEXT, metadata JSONB, created_at TIMESTAMP)` stores the final artefacts.
- **Web Server (Caddy)**: Serves a static gallery page that safely embeds generated HTML inside an iframe sandbox. The gallery lists items from the DB.
- **Deploy Service (Docker Compose)**: Orchestrates the database, generator, validator, and Caddy containers, providing zero‑downtime updates.

## Data Flow
1. **Spec → Issue Tracker** – Users create a ticket with a clear goal.
2. **Spec → Processor** – The backend polls the issue, extracts the *Goal* and *Acceptance criteria*.
3. **Processor → Generator** – Calls the LLM with a token‑budget limit defined in `PLAN.md`.
4. **Generator → Validator** – Sanitizes HTML, strips executable scripts, and enforces size limits.
5. **Validator → Database** – Persists the safe HTML and associated metadata.
6. **Database → Gallery (Caddy)** – The gallery queries the table and renders each entry inside an isolated iframe.

## Isolation & Safety
- Generated HTML is never served directly; it is always wrapped in an `<iframe sandbox="allow-scripts allow-same-origin">` to prevent XSS.
- The validator enforces a maximum of **500 KB** per HTML blob and strips any `<script>` tags.
- Model usage is capped per request (see `PLAN.md`) to protect the allowance and avoid runaway costs.

## Limits & Controls
- **Model token limit**: Configured per‑run; exceeds are truncated and flagged for manual review.
- **Retry attempts**: Hard‑capped at 3 retries before marking the ticket as blocked.
- **Rate limiting**: The processor respects GitHub API limits and backs off on 429 responses.
- **Database constraints**: Unique `spec_id` ensures one generated artefact per ticket.

## Deployment Sketch
```
services:
  db:
    image: postgres:15
    environment:
      POSTGRES_USER: agent
      POSTGRES_PASSWORD: secret
  generator:
    build: ./core/generator
    depends_on: [db]
  validator:
    build: ./core/validator
    depends_on: [generator]
  caddy:
    image: caddy:2
    volumes:
      - ./Caddyfile:/etc/caddy/Caddyfile
    depends_on: [db]
```

This architecture enables a thin, testable pipeline where each ticket maps to a single PR implementing one of the components above.
