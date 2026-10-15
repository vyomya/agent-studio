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
