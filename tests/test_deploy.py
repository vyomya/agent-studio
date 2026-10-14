import subprocess, os, pytest

def test_script_syntax():
    # Ensure the script passes bash syntax check
    result = subprocess.run(['bash', '-n', 'deploy/install.sh'], cwd=os.getcwd(), capture_output=True, text=True)
    assert result.returncode == 0, f"Syntax error: {result.stderr}"
