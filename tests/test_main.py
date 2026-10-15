"""Persistence, gallery order, and generated-page isolation tests."""

import os
import uuid

import psycopg
from psycopg.conninfo import make_conninfo
from psycopg import sql
import pytest
from fastapi.testclient import TestClient

from app import storage
from app.main import app


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


def test_invalid_spec_is_rejected_without_saving():
    with TestClient(app) as client:
        empty = client.post("/generate", data={"spec": ""})
        too_long = client.post("/generate", data={"spec": "x" * 501})

    assert empty.status_code == 400
    assert "Please enter" in empty.text
    assert too_long.status_code == 400
    assert "500 characters" in too_long.text
    assert storage.list_pages() == []
