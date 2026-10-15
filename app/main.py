"""FastAPI spec form and safe gallery for validated generated pages."""
from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

if __package__:  # Tests import app.main; the container runs main:app from /app.
    from .generator import Generator, GeneratorError
    from .limits import LimitExceeded, ModelBusy, model_request_slot
    from .retry import InvalidPageError, generate_valid_page
    from .storage import initialize_database, list_pages, save_page
else:  # pragma: no cover - exercised by the container's /app working directory.
    from generator import Generator, GeneratorError
    from limits import LimitExceeded, ModelBusy, model_request_slot
    from retry import InvalidPageError, generate_valid_page
    from storage import initialize_database, list_pages, save_page

@asynccontextmanager
async def lifespan(_: FastAPI):
    initialize_database()
    yield


app = FastAPI(lifespan=lifespan)
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent / "templates"))


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


def _gallery(request: Request, message: str | None = None, status_code: int = 200) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request,
        name="gallery.html",
        context={"pages": list_pages(), "message": message},
        status_code=status_code,
    )


def _visitor_id(request: Request) -> str:
    forwarded_for = request.headers.get("x-forwarded-for")
    if forwarded_for:
        first_address = forwarded_for.split(",", 1)[0].strip()
        if first_address:
            return first_address
    return request.client.host if request.client else "unknown"


@app.get("/", response_class=HTMLResponse)
def gallery(request: Request) -> HTMLResponse:
    return _gallery(request)


@app.post("/generate")
def generate(
    request: Request,
    spec: str = Form(default=""),
    style_example: str = Form(default=""),
):
    spec = spec.strip()
    if not spec:
        return _gallery(request, "Please enter a page description.", 400)
    if len(spec) > 500:
        return _gallery(request, "Page descriptions must be 500 characters or fewer.", 400)

    try:
        with model_request_slot(_visitor_id(request)):
            generate_valid_page(
                spec,
                Generator(),
                save_page,
                style_example=style_example.strip() or None,
            )
    except LimitExceeded:
        return _gallery(request, "You have reached the page limit, please try again later.", 429)
    except ModelBusy:
        return _gallery(request, "The service is currently busy. Please try again later.", 503)
    except InvalidPageError:
        return _gallery(request, "Could not build a valid page. Please try again.", 503)
    except GeneratorError:
        return _gallery(request, "The service is currently busy. Please try again later.", 503)
    return RedirectResponse(url="/", status_code=303)
