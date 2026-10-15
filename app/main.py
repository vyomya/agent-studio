"""Minimal FastAPI application for the thin deployable skeleton.

Provides a single ``GET /`` endpoint that returns a plain JSON response.
The implementation is deliberately tiny – just enough to be started by the
deployment script and to satisfy the acceptance criteria for issue #14.
"""

from fastapi import FastAPI

app = FastAPI()


@app.get("/")
def root() -> dict:
    """Health‑check endpoint returning a simple JSON payload.

    The public URL is expected to proxy to this endpoint via Caddy, so a
    ``200`` response here satisfies the ticket's requirement.
    """
    return {"status": "ok"}

