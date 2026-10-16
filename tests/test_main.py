"""Persistence, gallery order, and generated-page isolation tests."""

import os
import subprocess
import sys
import uuid
from unittest.mock import Mock
from pathlib import Path

import psycopg
from psycopg.conninfo import make_conninfo
from psycopg import sql
import pytest
from fastapi.testclient import TestClient

from app import limits, storage
from app import main as main_module
from app.generator import GeneratorError, MockProvider, ProviderResponse
from app.main import app
from app.retry import InvalidPageError


@pytest.fixture(autouse=True)
def clean_test_database(monkeypatch):
    test_url = os.getenv("DATABASE_URL_TEST")
    if not test_url:
        pytest.skip("DATABASE_URL_TEST is not configured")
    schema = "test_gallery_" + uuid.uuid4().hex
    with psycopg.connect(test_url) as connection:
        connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    isolated_url = make_conninfo(test_url, options=f"-c search_path={schema}")
    monkeypatch.setenv("DATABASE_URL", isolated_url)
    try:
        storage.initialize_database()
        yield
    finally:
        with psycopg.connect(test_url) as connection:
            connection.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


def test_saved_pages_survive_new_connection_and_gallery_is_newest_first():
    older = storage.save_page("Older spec", "<html>older</html>", 1)
    newer = storage.save_page(
        "Newer spec", "<html>newer</html>", 2,
        parent_id=older.id, version=2, refine_instruction="make it dark",
    )

    # Each storage call opens and closes its own connection; this read represents
    # a new app/database connection, not in-memory process state.
    pages = storage.list_pages()
    assert [page.id for page in pages] == [newer.id, older.id]
    assert pages[0].spec == "Newer spec"
    assert pages[0].attempts == 2
    assert pages[0].version == 2
    assert pages[0].parent_id == older.id
    assert pages[0].refine_instruction == "make it dark"
    assert pages[0].created_at is not None

    with TestClient(app) as client:
        response = client.get("/")
    with TestClient(app) as restarted_client:
        after_restart = restarted_client.get("/")
    assert response.status_code == 200
    assert response.text.index("Newer spec") < response.text.index("Older spec")
    assert after_restart.status_code == 200
    assert "Newer spec" in after_restart.text


def test_gallery_sandboxes_srcdoc_and_escapes_source_without_page_route():
    page_html = "<!doctype html><html><head><title>Safe</title></head><body><h1>Safe</h1><section>A</section><section>B</section><section>C</section></body></html>"
    saved = storage.save_page("Safe spec", page_html, 1)

    with TestClient(app) as client:
        response = client.get("/")
        page_route = client.get(f"/pages/{saved.id}")

    assert response.status_code == 200
    assert 'sandbox srcdoc="&lt;!doctype html&gt;' in response.text.lower()
    assert "allow-scripts" not in response.text
    assert "allow-same-origin" not in response.text
    assert "&lt;!doctype html&gt;" in response.text
    assert page_route.status_code == 404


def test_generate_saves_valid_page_then_redirects_to_gallery(monkeypatch):
    monkeypatch.setenv("GENERATOR_PROVIDER", "mock")
    monkeypatch.setenv("MOCK_RESPONSE", "valid")
    with TestClient(app) as client:
        response = client.post("/generate", data={"spec": "A simple gallery page"}, follow_redirects=False)
        gallery = client.get(response.headers["location"])

    assert response.status_code == 303
    assert gallery.status_code == 200
    assert "A simple gallery page" in gallery.text
    assert len(storage.list_pages()) == 1
    assert storage.list_pages()[0].attempts == 1


def test_spec_form_has_description_style_and_generate_controls():
    with TestClient(app) as client:
        response = client.get("/")

    assert response.status_code == 200
    assert '<form action="/generate" method="post">' in response.text
    assert 'name="spec" maxlength="500" required' in response.text
    assert 'name="style_example"' in response.text
    assert 'type="submit">Generate</button>' in response.text


def test_refinements_create_immutable_version_chain_and_gallery_labels(monkeypatch):
    monkeypatch.setenv("GENERATOR_PROVIDER", "mock")
    monkeypatch.setenv("MOCK_REFINE_RESPONSE", "valid")
    original_html = VALID_GENERATED_HTML
    original = storage.save_page("A pricing page", original_html, 1)

    with TestClient(app) as client:
        v2_response = client.post(
            f"/pages/{original.id}/refine",
            data={"instruction": "make it dark mode"},
            follow_redirects=False,
        )
        v2 = storage.list_pages()[0]
        v3_response = client.post(
            f"/pages/{v2.id}/refine",
            data={"instruction": "make the header larger"},
            follow_redirects=False,
        )
        gallery = client.get("/")

    assert v2_response.status_code == 303
    assert v3_response.status_code == 303
    v2, v3, unchanged_original = storage.get_page(v2.id), storage.list_pages()[0], storage.get_page(original.id)
    assert v2 is not None and v3 is not None and unchanged_original is not None
    assert v2.version == 2 and v2.parent_id == original.id
    assert v2.refine_instruction == "make it dark mode"
    assert "background: #111" in v2.html
    assert v3.version == 3 and v3.parent_id == v2.id
    assert v3.refine_instruction == "make the header larger"
    assert unchanged_original.html == original_html
    assert unchanged_original.version == 1 and unchanged_original.parent_id is None
    assert "v3 of 'A pricing page' · make the header larger" in gallery.text
    assert "v2 of 'A pricing page' · make it dark mode" in gallery.text
    assert gallery.text.index("v3 of 'A pricing page'") < gallery.text.index("v2 of 'A pricing page'")
    assert 'placeholder="make it dark mode"' in gallery.text
    assert 'name="instruction" maxlength="200"' in gallery.text


@pytest.mark.parametrize(
    ("outcome", "expected_error"),
    [
        ("missing_sections", "Expected at least three <section> elements, found 0."),
        ("script", "<script> tags are not allowed."),
    ],
)
def test_invalid_refinement_retries_three_times_without_saving(monkeypatch, outcome, expected_error):
    monkeypatch.setenv("GENERATOR_PROVIDER", "mock")
    monkeypatch.setenv("MOCK_REFINE_RESPONSE", outcome)
    original = storage.save_page("Original spec", VALID_GENERATED_HTML, 1)
    calls = []
    mock_call = MockProvider.call

    def track_call(provider, messages):
        calls.append(messages)
        return mock_call(provider, messages)

    monkeypatch.setattr(MockProvider, "call", track_call)
    with TestClient(app) as client:
        response = client.post(
            f"/pages/{original.id}/refine",
            data={"instruction": "make it dark mode"},
        )

    assert response.status_code == 503
    assert "Could not build a valid page" in response.text
    assert len(calls) == 3
    assert VALID_GENERATED_HTML in calls[0][1]["content"]
    assert expected_error in calls[1][1]["content"]
    pages = storage.list_pages()
    assert [page.id for page in pages] == [original.id]
    assert storage.get_page(original.id).html == VALID_GENERATED_HTML


def test_invalid_refinement_instruction_is_rejected_without_model_call(monkeypatch):
    monkeypatch.setenv("GENERATOR_PROVIDER", "mock")
    original = storage.save_page("Original spec", VALID_GENERATED_HTML, 1)
    mock_call = Mock()
    monkeypatch.setattr(MockProvider, "call", mock_call)

    with TestClient(app) as client:
        empty = client.post(f"/pages/{original.id}/refine", data={"instruction": " "})
        too_long = client.post(
            f"/pages/{original.id}/refine", data={"instruction": "x" * 201}
        )

    assert empty.status_code == 400 and "enter a refinement instruction" in empty.text
    assert too_long.status_code == 400 and "200 characters" in too_long.text
    mock_call.assert_not_called()
    assert storage.list_pages() == [original]


def test_refinement_consumes_per_visitor_allowance_before_model_call(monkeypatch):
    visitor_id = f"refine-visitor-limit-{uuid.uuid4().hex}"
    monkeypatch.setenv("GENERATOR_PROVIDER", "mock")
    monkeypatch.setenv("MOCK_RESPONSE", "valid")
    monkeypatch.setenv("MOCK_REFINE_RESPONSE", "valid")
    monkeypatch.setenv("MODEL_LIMIT_PER_HOUR", "1")
    monkeypatch.setenv("MODEL_LIMIT_PER_DAY", "20")
    monkeypatch.setenv("GLOBAL_MODEL_DAILY_LIMIT", "10000")
    calls = []
    mock_call = MockProvider.call

    def track_call(provider, messages):
        calls.append(messages)
        return mock_call(provider, messages)

    monkeypatch.setattr(MockProvider, "call", track_call)
    headers = {"X-Forwarded-For": visitor_id}
    with TestClient(app) as client:
        generated = client.post("/generate", data={"spec": "A page"}, headers=headers, follow_redirects=False)
        original = storage.list_pages()[0]
        refined = client.post(
            f"/pages/{original.id}/refine", data={"instruction": "make it dark mode"}, headers=headers
        )

    assert generated.status_code == 303
    assert refined.status_code == 429
    assert "page limit" in refined.text
    assert len(calls) == 1
    assert len(storage.list_pages()) == 1


def test_refinement_consumes_global_daily_allowance_before_model_call(monkeypatch):
    monkeypatch.setenv("GENERATOR_PROVIDER", "mock")
    monkeypatch.setenv("MOCK_RESPONSE", "valid")
    monkeypatch.setenv("MOCK_REFINE_RESPONSE", "valid")
    monkeypatch.setenv("MODEL_LIMIT_PER_HOUR", "5")
    monkeypatch.setenv("MODEL_LIMIT_PER_DAY", "20")
    monkeypatch.setenv("GLOBAL_MODEL_DAILY_LIMIT", "1")
    calls = []
    mock_call = MockProvider.call

    def track_call(provider, messages):
        calls.append(messages)
        return mock_call(provider, messages)

    monkeypatch.setattr(MockProvider, "call", track_call)
    with TestClient(app) as client:
        generated = client.post(
            "/generate", data={"spec": "A page"},
            headers={"X-Forwarded-For": f"global-source-{uuid.uuid4().hex}"},
            follow_redirects=False,
        )
        original = storage.list_pages()[0]
        refined = client.post(
            f"/pages/{original.id}/refine",
            data={"instruction": "make it dark mode"},
            headers={"X-Forwarded-For": f"global-refiner-{uuid.uuid4().hex}"},
        )

    assert generated.status_code == 303
    assert refined.status_code == 429
    assert len(calls) == 1
    assert len(storage.list_pages()) == 1


def test_invalid_spec_is_rejected_without_model_call_or_saving(monkeypatch):
    calls = install_mock_responses(monkeypatch, [VALID_GENERATED_HTML])
    with TestClient(app) as client:
        empty = client.post("/generate", data={"spec": ""})
        too_long = client.post("/generate", data={"spec": "x" * 501})

    assert empty.status_code == 400
    assert "Please enter" in empty.text
    assert too_long.status_code == 400
    assert "500 characters" in too_long.text
    assert calls == []
    assert storage.list_pages() == []


@pytest.mark.parametrize(
    ("failure", "message"),
    [
        (InvalidPageError(3, ["invalid"]), "Could not build a valid page"),
        (GeneratorError("provider unavailable"), "service is currently busy"),
    ],
)
def test_generate_shows_distinct_validation_and_provider_failures(monkeypatch, failure, message):
    monkeypatch.setenv("GENERATOR_PROVIDER", "mock")
    monkeypatch.setattr(main_module, "generate_valid_page", lambda *args, **kwargs: (_ for _ in ()).throw(failure))

    with TestClient(app) as client:
        response = client.post("/generate", data={"spec": "A page"})

    assert response.status_code == 503
    assert message in response.text


def test_container_style_main_module_imports_from_app_directory():
    app_dir = Path(__file__).resolve().parents[1] / "app"
    result = subprocess.run(
        [sys.executable, "-c", "import main; assert main.app is not None"],
        cwd=app_dir,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


VALID_GENERATED_HTML = """<!doctype html><html><head><title>Example</title></head><body>
<h1>Example</h1><section>One</section><section>Two</section><section>Three</section>
</body></html>"""


def install_mock_responses(monkeypatch, responses):
    monkeypatch.setenv("GENERATOR_PROVIDER", "mock")
    responses = iter(responses)
    calls = []

    def respond(_provider, messages):
        calls.append(messages)
        return ProviderResponse(status_code=200, content=next(responses))

    monkeypatch.setattr(MockProvider, "call", respond)
    return calls


def test_retries_spend_one_visitor_generation_allowance(monkeypatch):
    visitor_id = f"retry-allowance-{uuid.uuid4().hex}"
    invalid = "<html><body><h1>Incomplete</h1></body></html>"
    calls = install_mock_responses(monkeypatch, [invalid, invalid, VALID_GENERATED_HTML])
    monkeypatch.setenv("MODEL_LIMIT_PER_HOUR", "5")
    monkeypatch.setenv("MODEL_LIMIT_PER_DAY", "20")
    monkeypatch.setenv("GLOBAL_MODEL_DAILY_LIMIT", "10000")

    with TestClient(app) as client:
        response = client.post("/generate", data={"spec": "A page"}, headers={"X-Forwarded-For": visitor_id}, follow_redirects=False)

    assert response.status_code == 303
    assert len(calls) == 3
    with psycopg.connect(os.environ["DATABASE_URL"]) as connection:
        row = connection.execute(
            "SELECT hour_count, day_count FROM model_limits WHERE visitor_ip = %s",
            (visitor_id,),
        ).fetchone()
    assert row == (1, 1)
    assert storage.list_pages()[0].attempts == 3


def test_sixth_generate_from_forwarded_ip_is_rejected_without_model_call(monkeypatch):
    visitor_id = f"hourly-limit-{uuid.uuid4().hex}"
    calls = install_mock_responses(monkeypatch, [VALID_GENERATED_HTML] * 5)
    monkeypatch.setenv("MODEL_LIMIT_PER_HOUR", "5")
    monkeypatch.setenv("MODEL_LIMIT_PER_DAY", "20")
    monkeypatch.setenv("GLOBAL_MODEL_DAILY_LIMIT", "10000")

    with TestClient(app) as client:
        responses = [
            client.post("/generate", data={"spec": f"Page {i}"}, headers={"X-Forwarded-For": f"{visitor_id}, 10.0.0.1"}, follow_redirects=False)
            for i in range(6)
        ]

    assert [response.status_code for response in responses[:5]] == [303] * 5
    assert responses[5].status_code == 429
    assert "You have reached the page limit, please try again later." in responses[5].text
    assert len(calls) == 5


def test_forwarded_visitors_have_separate_allowances(monkeypatch):
    visitor_ids = [f"visitor-a-{uuid.uuid4().hex}", f"visitor-b-{uuid.uuid4().hex}"]
    calls = install_mock_responses(monkeypatch, [VALID_GENERATED_HTML] * 2)
    monkeypatch.setenv("MODEL_LIMIT_PER_HOUR", "1")
    monkeypatch.setenv("MODEL_LIMIT_PER_DAY", "20")
    monkeypatch.setenv("GLOBAL_MODEL_DAILY_LIMIT", "10000")

    with TestClient(app) as client:
        responses = []
        for visitor_id in visitor_ids:
            headers = {"X-Forwarded-For": visitor_id}
            responses.append(client.post("/generate", data={"spec": "First"}, headers=headers, follow_redirects=False))
            responses.append(client.post("/generate", data={"spec": "Second"}, headers=headers, follow_redirects=False))

    assert [response.status_code for response in responses] == [303, 429, 303, 429]
    assert len(calls) == 2


def test_held_generation_slot_returns_busy_without_spending_allowance(monkeypatch):
    visitor_id = f"busy-slot-{uuid.uuid4().hex}"
    calls = install_mock_responses(monkeypatch, [VALID_GENERATED_HTML])
    monkeypatch.setenv("MODEL_LIMIT_PER_HOUR", "5")
    monkeypatch.setenv("MODEL_LIMIT_PER_DAY", "20")
    monkeypatch.setenv("GLOBAL_MODEL_DAILY_LIMIT", "10000")

    with psycopg.connect(os.environ["DATABASE_URL"]) as lock_connection:
        lock_connection.execute(limits._CREATE_TABLE)
        lock_connection.execute("SELECT pg_advisory_lock(%s)", (limits._GENERATION_LOCK_KEY,))
        with TestClient(app) as client:
            response = client.post("/generate", data={"spec": "A page"}, headers={"X-Forwarded-For": visitor_id})
        lock_connection.execute("SELECT pg_advisory_unlock(%s)", (limits._GENERATION_LOCK_KEY,))

    assert response.status_code == 503
    assert "service is currently busy" in response.text
    assert calls == []
    with psycopg.connect(os.environ["DATABASE_URL"]) as connection:
        row = connection.execute(
            "SELECT hour_count, day_count FROM model_limits WHERE visitor_ip = %s",
            (visitor_id,),
        ).fetchone()
    assert row is None
