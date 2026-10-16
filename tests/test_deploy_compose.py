from __future__ import annotations

from pathlib import Path
import re

import pytest

ROOT = Path(__file__).resolve().parents[1]
COMPOSE_PATH = ROOT / "deploy/docker-compose.yml"


def load_compose() -> dict:
    yaml = pytest.importorskip("yaml")
    return yaml.safe_load(COMPOSE_PATH.read_text(encoding="utf-8"))


def test_compose_defines_app_postgres_and_caddy_services() -> None:
    compose = load_compose()
    services = compose["services"]
    assert {"app", "db", "caddy"} <= services.keys()
    assert services["app"]["image"] == "agent-studio-app:latest"
    assert services["app"]["build"]["context"] == "../app"
    assert services["db"]["image"] == "postgres:16"
    assert services["caddy"]["image"] == "caddy:2"


def test_app_settings_and_caddy_upstream_are_configured() -> None:
    compose = load_compose()
    services = compose["services"]
    app = services["app"]
    caddy = services["caddy"]

    assert app["environment"]["DATABASE_URL"]
    assert app["env_file"] == [{"path": ".env", "required": False}]
    assert "env_file" not in caddy
    assert caddy["environment"]["DOMAIN"] == "${DOMAIN:-localhost}"

    caddyfile = (ROOT / "deploy/Caddyfile").read_text(encoding="utf-8")
    upstream = re.search(r"(?m)^\s*reverse_proxy\s+([A-Za-z0-9_.-]+):(\d+)\s*$", caddyfile)
    assert upstream is not None, "Caddyfile must define a named service upstream"
    service_name, port = upstream.groups()
    assert service_name in services
    assert service_name == "app"
    assert port == "8000"
    assert "../app:/app:ro" in app["volumes"]
    assert "./Caddyfile:/etc/caddy/Caddyfile:ro" in caddy["volumes"]


def test_public_ports_networks_and_persistent_data_are_configured() -> None:
    compose = load_compose()
    services = compose["services"]
    assert "80:80" in services["caddy"]["ports"]
    assert "443:443" in services["caddy"]["ports"]
    assert "443:443/udp" in services["caddy"]["ports"]
    assert "8000" in services["app"]["expose"]
    assert "postgres_data:/var/lib/postgresql/data" in services["db"]["volumes"]
    assert "caddy_data:/data" in services["caddy"]["volumes"]
    assert "caddy_config:/config" in services["caddy"]["volumes"]
    assert services["app"]["networks"] == ["frontend", "backend"]
    assert compose["networks"]["backend"]["internal"] is True


def test_architecture_document_links_compose_file() -> None:
    architecture = (ROOT / "docs/ARCHITECTURE.md").read_text(encoding="utf-8")
    assert "../deploy/docker-compose.yml" in architecture
