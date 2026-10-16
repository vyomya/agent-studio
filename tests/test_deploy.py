from pathlib import Path
import subprocess


def test_install_script_syntax() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        ["bash", "-n", str(repo_root / "deploy" / "install.sh")],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_installer_health_check_uses_local_caddy_and_domain() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    installer = (repo_root / "deploy" / "install.sh").read_text(encoding="utf-8")
    assert 'DOMAIN="$(awk' in installer
    assert '--resolve "$DOMAIN:443:127.0.0.1"' in installer
    assert '"https://$DOMAIN/"' in installer
    assert 'for _ in {1..120}' in installer
    assert "DEPLOY_URL:-" in installer


def test_installer_generates_postgres_password_only_when_missing() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    installer = (repo_root / "deploy" / "install.sh").read_text(encoding="utf-8")
    assert "grep -qE '^[[:space:]]*POSTGRES_PASSWORD='" in installer
    assert 'openssl rand -hex 24' in installer
    assert "printf 'POSTGRES_PASSWORD=%s" in installer
