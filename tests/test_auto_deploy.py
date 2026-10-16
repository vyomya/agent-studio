from __future__ import annotations

import os
from pathlib import Path
import pwd
import shutil
import subprocess
import tempfile

import pytest


ROOT = Path(__file__).resolve().parents[1]
WORKER = ROOT / "deploy" / "auto-deploy.sh"


def _git(*args: str, cwd: Path) -> str:
    result = subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def _make_checkout(tmp_path: Path) -> tuple[Path, Path]:
    remote = tmp_path / "origin.git"
    checkout = tmp_path / "checkout"
    subprocess.run(["git", "init", "--bare", str(remote)], check=True, capture_output=True)
    checkout.mkdir()
    subprocess.run(
        ["git", "init", "--initial-branch=main"],
        cwd=checkout,
        check=True,
        capture_output=True,
    )
    _git("config", "user.name", "Test", cwd=checkout)
    _git("config", "user.email", "test@example.invalid", cwd=checkout)
    (checkout / "deploy").mkdir()
    shutil.copy2(WORKER, checkout / "deploy" / "auto-deploy.sh")
    (checkout / "version.txt").write_text("initial\n", encoding="utf-8")
    _git("add", "deploy/auto-deploy.sh", "version.txt", cwd=checkout)
    _git("commit", "-m", "initial", cwd=checkout)
    _git("remote", "add", "origin", str(remote), cwd=checkout)
    _git("push", "-u", "origin", "main", cwd=checkout)
    return checkout, remote


def _run_worker(tmp_path: Path, checkout: Path) -> subprocess.CompletedProcess[str]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    log = tmp_path / "systemctl.log"
    stub = bin_dir / "systemctl"
    stub.write_text("#!/bin/sh\nprintf '%s\\n' \"$*\" >> \"$SYSTEMCTL_LOG\"\n", encoding="utf-8")
    stub.chmod(0o755)
    env = os.environ.copy()
    env.update(
        {
            "AGENT_STUDIO_REPO": str(checkout),
            "AGENT_STUDIO_LOCK_FILE": str(tmp_path / "worker.lock"),
            "PATH": f"{bin_dir}{os.pathsep}{env['PATH']}",
            "SYSTEMCTL_LOG": str(log),
        }
    )
    result = subprocess.run(
        ["bash", str(checkout / "deploy" / "auto-deploy.sh")],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    result.systemctl_log = log  # type: ignore[attr-defined]
    return result


def test_auto_deploy_fast_forwards_and_restarts_only_when_main_advances(
    tmp_path: Path,
) -> None:
    checkout, remote = _make_checkout(tmp_path)
    result = _run_worker(tmp_path, checkout)
    assert result.returncode == 0, result.stderr
    assert not result.systemctl_log.exists()

    upstream = tmp_path / "upstream"
    subprocess.run(
        ["git", "clone", "--branch", "main", str(remote), str(upstream)],
        check=True,
        capture_output=True,
    )
    _git("config", "user.name", "Test", cwd=upstream)
    _git("config", "user.email", "test@example.invalid", cwd=upstream)
    (upstream / "version.txt").write_text("updated\n", encoding="utf-8")
    _git("commit", "-am", "advance main", cwd=upstream)
    _git("push", "origin", "main", cwd=upstream)
    target = _git("rev-parse", "HEAD", cwd=upstream)

    result = _run_worker(tmp_path, checkout)
    assert result.returncode == 0, result.stderr
    assert _git("rev-parse", "HEAD", cwd=checkout) == target
    assert result.systemctl_log.read_text(encoding="utf-8").splitlines() == [
        "restart agent-studio.service"
    ]


def test_auto_deploy_refuses_local_changes_without_restarting(tmp_path: Path) -> None:
    checkout, _ = _make_checkout(tmp_path)
    (checkout / "version.txt").write_text("keep me" + chr(10), encoding="utf-8")

    result = _run_worker(tmp_path, checkout)

    assert result.returncode != 0
    assert "local changes" in result.stderr
    assert not result.systemctl_log.exists()


def test_auto_deploy_ignores_untracked_artifacts(tmp_path: Path) -> None:
    checkout, _ = _make_checkout(tmp_path)
    cache = checkout / "app" / "__pycache__"
    cache.mkdir(parents=True)
    (cache / "stray.pyc").write_bytes(b"not a deploy change")

    result = _run_worker(tmp_path, checkout)

    assert result.returncode == 0, result.stderr
    assert "already at origin/main" in result.stdout
    assert not result.systemctl_log.exists()


def test_auto_deploy_fast_forwards_checkout_owned_by_non_root() -> None:
    if os.geteuid() != 0:
        pytest.skip("chown-based deploy ownership test requires root")
    try:
        owner = pwd.getpwnam("nobody")
    except KeyError:
        pytest.skip("nobody user is unavailable")

    with tempfile.TemporaryDirectory(prefix="agent-studio-auto-deploy-") as directory:
        root = Path(directory)
        root.chmod(0o755)
        checkout, remote = _make_checkout(root)
        upstream = root / "upstream"
        subprocess.run(
            ["git", "clone", "--branch", "main", str(remote), str(upstream)],
            check=True,
            capture_output=True,
        )
        _git("config", "user.name", "Test", cwd=upstream)
        _git("config", "user.email", "test@example.invalid", cwd=upstream)
        (upstream / "version.txt").write_text("owned update" + chr(10), encoding="utf-8")
        _git("commit", "-am", "advance main", cwd=upstream)
        _git("push", "origin", "main", cwd=upstream)
        target = _git("rev-parse", "HEAD", cwd=upstream)

        for path in sorted(root.rglob("*"), key=lambda item: len(item.parts), reverse=True):
            os.chown(path, owner.pw_uid, owner.pw_gid)
        os.chown(root, owner.pw_uid, owner.pw_gid)

        result = _run_worker(root, checkout)
        assert result.returncode == 0, result.stderr
        assert _git("rev-parse", "HEAD", cwd=checkout) == target
        assert (checkout / "version.txt").read_text(encoding="utf-8") == "owned update" + chr(10)
        assert result.systemctl_log.read_text(encoding="utf-8").splitlines() == [
            "restart agent-studio.service"
        ]


def test_installer_enables_five_minute_auto_deploy_timer() -> None:
    service = (ROOT / "deploy" / "agent-studio-auto-deploy.service").read_text(
        encoding="utf-8"
    )
    timer = (ROOT / "deploy" / "agent-studio-auto-deploy.timer").read_text(
        encoding="utf-8"
    )
    installer = (ROOT / "deploy" / "install.sh").read_text(encoding="utf-8")
    assert "OnBootSec=2min" in timer
    assert "OnUnitActiveSec=5min" in timer
    assert "Unit=agent-studio-auto-deploy.service" in timer
    assert "systemctl enable --now agent-studio-auto-deploy.timer" in installer
    assert "auto-deploy.sh" in service


def test_deployment_scripts_have_valid_bash_syntax() -> None:
    result = subprocess.run(
        ["bash", "-n", str(ROOT / "deploy" / "install.sh"), str(WORKER)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_auto_deploy_systemd_units_verify() -> None:
    analyzer = shutil.which("systemd-analyze")
    if analyzer is None:
        pytest.skip("systemd-analyze is not installed")
    result = subprocess.run(
        [
            analyzer,
            "verify",
            str(ROOT / "deploy" / "agent-studio-auto-deploy.service"),
            str(ROOT / "deploy" / "agent-studio-auto-deploy.timer"),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
