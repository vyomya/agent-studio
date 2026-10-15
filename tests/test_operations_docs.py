from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "docs" / "OPERATIONS.md"


def test_operations_guide_covers_ubuntu_install_and_manual_installer():
    text = DOC.read_text()
    assert "Ubuntu 24.04" in text
    assert "sudo deploy/install.sh" in text
    assert "Docker" in text and "Compose" in text


def test_operations_guide_documents_systemd_lifecycle_and_logs():
    text = DOC.read_text()
    for command in (
        "systemctl start agent-studio.service",
        "systemctl stop agent-studio.service",
        "systemctl restart agent-studio.service",
        "systemctl status agent-studio.service",
        "journalctl -u agent-studio.service",
    ):
        assert command in text


def test_operations_guide_documents_reboot_and_service_verification():
    text = DOC.read_text()
    assert "sudo reboot" in text
    assert "systemctl is-enabled docker agent-studio.service" in text
    assert "systemctl is-active docker agent-studio.service" in text
    assert "curl -fsS https://<ip-with-dashes>.sslip.io/" in text


def test_operations_guide_links_to_compose_file():
    text = DOC.read_text()
    match = re.search(r"\[[^]]+\]\(([^)]+docker-compose\.yml)\)", text)
    assert match is not None
    assert (DOC.parent / match.group(1)).resolve() == (ROOT / "deploy" / "docker-compose.yml").resolve()
    assert (ROOT / "deploy" / "docker-compose.yml").is_file()
