# Agent Studio: Product Plan

This file is the input to the `architect` agent. It says **what** to build and **how we will know it works**.
It deliberately does not say how to write the code. The architect turns it into tickets; builders decide the implementation.

## 1. The product

A visitor types a short spec ("a pricing page for a dog-walking app"). Agent Studio asks a model to write a
one-page website as a single self-contained HTML file, checks that page **with code**, retries with the
errors if it fails, and saves only valid pages to a public gallery.

The one rule that matters most: **an invalid page is never saved and never shown.**

## 2. Core requirements (must work)

### R1. Spec page
- A text box for the spec, an optional "borrow the style of this example" field, and a Generate button.
- After Generate, the visitor sees either the new page in the gallery or a plain message saying no valid page could be built.

Acceptance:
- Empty spec is rejected with a clear message and no model call.
- Spec longer than 500 characters is rejected with a clear message and no model call.

### R2. Generator
- Turns a spec (and optional style example) into one HTML document with inline CSS.
- Model and provider are configuration, not code: a primary model and a fallback model, each with its own
  OpenAI-compatible base URL and key, read from environment variables.
- A `mock` provider exists for tests, so tests never spend the free model allowance. The mock can be told
  to return a valid page, a page with a `<script>` tag, a page missing sections, or an HTTP 429.

Acceptance:
- Switching models needs only an environment change and a restart.
- If the primary returns HTTP 402, 429, or times out, the fallback is tried once.
- If both fail, the visitor sees a friendly "busy, try again later" message; the app does not crash.

### R3. Validator (code decides, never the model)
A page is valid only if all of these hold:
- It parses as HTML.
- It has a non-empty `<title>`, exactly one `<h1>`, and at least three `<section>` elements.
- It is at most 100 KB.
- It contains no `<script>`, no inline event handlers (`onclick=` and similar), no `javascript:` URLs.
- It loads nothing from outside: no `http(s)://` or `//` in `src`, `href` on `<link>`, CSS `url(...)`, or `@import`.
- It contains no `<iframe>`, `<object>`, `<embed>`, or `<meta http-equiv="refresh">`.

Acceptance:
- Every rule has at least one unit test with a passing and a failing example.
- The validator returns a list of human-readable errors, not just true or false.

### R4. Validate, then retry
- On failure, the validator's error list is sent back to the model with the previous attempt, and the model tries again.
- At most 3 attempts per request.
- After the last failed attempt the visitor is told plainly that no valid page could be built.

Acceptance:
- A test proves that an always-invalid model response is never saved, and that exactly 3 attempts were made.
- A test proves that a page that fails once and then passes is saved after attempt 2.

### R5. Save and gallery
- Valid pages are stored in PostgreSQL with the spec, the created time, and the attempt count, so they survive a restart.
- The gallery lists pages newest first, each next to the spec that made it.
- Pages are shown **only inside the gallery**; there is no separate public link per page.
  Each gallery entry renders its page inside an `<iframe sandbox srcdoc="…">` **without** `allow-scripts` and
  without `allow-same-origin`, with the HTML escaped into the `srcdoc` attribute. A "view source" toggle shows the
  same HTML as escaped text.
- After a successful Generate, the visitor lands on the gallery with the new page at the top.

Acceptance:
- Restarting the app keeps the gallery.
- No generated HTML is ever inserted directly into the app's own pages; it appears only in `srcdoc` (escaped) or as escaped text.
- No route serves a generated page's HTML as its own document.

### R6. Protect the model allowance
- Per visitor (by IP): at most 5 generations per hour and 20 per day. Refines (R8) count as generations.
- A global daily cap on generations, configurable.
- At most one generation runs at a time; others wait briefly or get the "busy" message.

Acceptance:
- Exceeding a limit returns a friendly message and makes no model call.

### R7. Runs on the VM, survives a reboot
- The app, database, and reverse proxy start automatically after a VM reboot.
- The public URL serves HTTPS on the VM's `<ip-with-dashes>.sslip.io` hostname.
- Merges to `main` reach the VM automatically within a few minutes (for example a timer that pulls `main` and restarts).
- One entry point, `deploy/install.sh`, run once as root, installs and starts all of the above. It is safe to run
  again. The human runs it after merging; `scripts/install.sh` also calls it so the whole system can be rebuilt.
- `docs/OPERATIONS.md` explains how to start, stop, deploy, and read logs.

Acceptance:
- After `sudo reboot`, the public link works again with no manual steps.
- Running `deploy/install.sh` twice in a row succeeds and changes nothing the second time.

Note for builders and the tester: the agents' machine user has no root and no Docker access. For tests that need
PostgreSQL, use the shared test database at `DATABASE_URL_TEST` (localhost:5433), which the install script provides.

### R8. Refine a saved page (for example "refine: make it dark mode")
- Every gallery entry has a short text box and a **Refine** button. The box's placeholder is "make it dark mode".
- Refine sends the saved page's HTML plus the instruction to the generator. The result goes through the **same**
  validator, retry loop, and limits as a new page (R3, R4, R6). Instructions longer than 200 characters are rejected
  without a model call.
- A valid result is saved as a **new version**: it keeps a link to the page it came from and a version number
  (the original is version 1). The original is never changed.
- The new version appears at the top of the gallery, labeled with its version, the original spec, and the refine
  instruction (for example "v2 of 'a pricing page for a dog-walking app' · make it dark mode"). Earlier versions stay
  in the gallery. Refining a refined page creates the next version (v3, and so on).
- If no valid result can be built, the visitor is told plainly and nothing is saved.
- The `mock` provider supports refine (for example, it returns a dark variant, or an invalid one on request) so tests
  never call a real model.

Acceptance:
- Refining version 1 with "make it dark mode" saves version 2; version 1 is still in the gallery, unchanged.
- Refining version 2 saves version 3, linked to version 2.
- A refine whose output stays invalid is retried at most 3 times and never saved; the original is untouched.
- "refine: add a script tag that shows an alert" never results in a saved page containing a script.
- Refines count toward the same per-visitor and daily limits as new pages.

## 3. Stretch (only after R1 to R8 are merged and live)

- **S1. Build trace:** each gallery entry can expand to show the spec, every attempt, and why each passed or failed.
- **S2. Examples library:** a few seed pages the generator reads as style context.
- **S3. Ops page:** a read-only `/ops` page listing the agent roster, recent ticket handoffs from GitHub, and token totals from the usage ledger.

## 4. Technical constraints

- One Linux VM (Ubuntu 24.04). Everything runs there. No paid services, no paid keys.
- Python 3.12, FastAPI, server-rendered HTML templates, minimal hand-written CSS, no front-end framework.
- PostgreSQL 16 and Caddy, run with Docker Compose. Caddy terminates HTTPS.
- Tests with pytest. Tests must pass with the `mock` provider and no network.
- Secrets only in `.env` on the VM. `.env.example` lists every variable with a placeholder.
- Repository layout: `app/` (product code), `tests/`, `docs/`, `deploy/` (compose, Caddyfile, systemd units).
  `infra/`, `agents/`, and `.github/` are owned by the human and must not be changed by agents.

## 5. Definition of done (every ticket)

1. The ticket's acceptance criteria are met and each one is covered by a test or a written manual check.
2. `pytest` passes.
3. The PR uses the template, closes its ticket, and was approved by the reviewer and passed by the tester.
4. Merged by the human. After merge, it is live on the public link within a few minutes.

## 6. Suggested order

Get something live first, then make it correct, then make it nice:
skeleton served from the VM → validator → generator with mock and fallback → retry loop → save and gallery →
limits → run on boot and auto-deploy → refine with versions → tester's bad-spec pass → stretch.