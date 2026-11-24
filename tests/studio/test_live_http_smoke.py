"""Launch the actual local server, rather than a mocked UI endpoint."""
import json
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[2]


def test_real_localhost_startup(tmp_path):
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    workspace = tmp_path / "isolated"
    origin = f"http://127.0.0.1:{port}"
    process = subprocess.Popen(
        [sys.executable, "-B", str(ROOT / "tools/studio_local_bridge.py"),
         "--port", str(port), "--workspace", str(workspace)],
        cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        deadline = time.monotonic() + 15
        while True:
            assert process.poll() is None, "Studio server stopped unexpectedly"
            try:
                with urlopen(origin + "/api/status", timeout=1) as response:
                    status = json.load(response)
                break
            except OSError:
                assert time.monotonic() < deadline, "Studio server did not become ready"
                time.sleep(0.1)
        assert status["token"]
        assert not status["connected"]
        assert not status["active_job"]
        with urlopen(origin + "/", timeout=2) as response:
            assert "CutScene Studio" in response.read().decode()
        with urlopen(origin + "/cinematic.js", timeout=2) as response:
            assert "function canExecute" in response.read().decode()
        data = json.dumps({"unity_folder": "", "unreal_folder": ""}).encode()
        req = Request(origin + "/api/discover", data=data, headers={
            "Content-Type": "application/json", "X-CSAI-Token": status["token"],
        })
        with urlopen(req, timeout=2) as response:
            assert not json.load(response)["ready"]
        assert not list(workspace.glob("jobs/*.json"))
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
