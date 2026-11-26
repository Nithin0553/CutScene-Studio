"""Check the real Windows launcher without starting the Studio server."""

import shutil
import subprocess
import sys
from pathlib import Path

import pytest


REPO = Path(__file__).resolve().parents[2]


@pytest.mark.skipif(sys.platform != "win32", reason="Windows PowerShell launcher")
def test_check_only_uses_explicit_storage_root(tmp_path):
    powershell = shutil.which("powershell.exe")
    python = REPO / ".venv-studio" / "Scripts" / "python.exe"
    if not powershell or not python.is_file():
        pytest.skip("requires PowerShell and the installed Studio virtual environment")

    root = tmp_path / "storage root with spaces"
    result = subprocess.run(
        [
            powershell,
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(REPO / "tools" / "start_studio.ps1"),
            "-StorageRoot",
            str(root),
            "-CheckOnly",
        ],
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=90,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    expected = {
        "Storage root": root,
        "Run workspace": root / "runs",
        "PIP_CACHE_DIR": root / "cache" / "pip",
        "npm_config_cache": root / "cache" / "npm",
        "HF_HOME": root / "cache" / "huggingface",
        "UPM_CACHE_ROOT": root / "cache" / "unity",
        "TEMP": root / "temp",
        "TMP": root / "temp",
    }
    for key, directory in expected.items():
        assert f"{key}: {directory}" in result.stdout
        assert directory.is_dir()
    assert "Studio was not started." in result.stdout
    assert "Open http://" not in result.stdout
