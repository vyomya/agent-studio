from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMPOSE = (ROOT / "deploy/docker-compose.yml").read_text()


def test_compose_defines_app_postgres_and_caddy_services():
    assert "  app:" in COMPOSE
    assert "  db:" in COMPOSE
    assert "  caddy:" in COMPOSE
    assert "image: agent-studio-app:latest" in COMPOSE
    assert "context: ../app" in COMPOSE
    assert "image: postgres:16" in COMPOSE
    assert "image: caddy:latest" in COMPOSE


def test_app_and_caddy_configuration_are_mounted():
    assert "../app:/app:ro" in COMPOSE
    assert "./Caddyfile:/etc/caddy/Caddyfile:ro" in COMPOSE
    assert "DATABASE_URL:" in COMPOSE
    assert "DOMAIN:" in COMPOSE


def test_public_ports_and_persistent_data_are_configured():
    assert '"80:80"' in COMPOSE
    assert '"443:443"' in COMPOSE
    assert '"443:443/udp"' in COMPOSE
    assert "postgres_data:/var/lib/postgresql/data" in COMPOSE
    assert "caddy_data:/data" in COMPOSE
    assert "caddy_config:/config" in COMPOSE
    assert "      - frontend" in COMPOSE
    assert "      - backend" in COMPOSE
    assert "    internal: true" in COMPOSE


def test_architecture_document_links_compose_file():
    architecture = (ROOT / "docs/ARCHITECTURE.md").read_text()
    assert "../deploy/docker-compose.yml" in architecture
