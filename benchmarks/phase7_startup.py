"""Measure a fresh loopback Streamlit listener; no page/session or remote traffic."""

import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
start = time.perf_counter()
process = subprocess.Popen(
    [
        sys.executable,
        "-m",
        "streamlit",
        "run",
        "streamlit_app.py",
        "--server.address",
        "127.0.0.1",
        "--server.port",
        "8520",
        "--server.headless",
        "true",
        "--browser.gatherUsageStats",
        "false",
    ],
    cwd=ROOT,
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL,
)
try:
    while time.perf_counter() - start < 20:
        if process.poll() is not None:
            raise RuntimeError("Streamlit exited before readiness")
        try:
            with urllib.request.urlopen(
                "http://127.0.0.1:8520/_stcore/health", timeout=0.5
            ) as response:
                if response.status == 200:
                    result = {
                        "listener_ready_seconds": time.perf_counter() - start,
                        "method": "Fresh process to HTTP health 200; 50 ms polling",
                        "scope": "HTTP listener only; lazy first-session import excluded",
                        "first_session_import_reference": "phase7-performance.json: web imports",
                    }
                    (ROOT / "benchmarks/phase7-startup.json").write_text(
                        json.dumps(result, indent=2) + "\n"
                    )
                    print(json.dumps(result))
                    break
        except (urllib.error.URLError, TimeoutError):
            pass
        time.sleep(0.05)
    else:
        raise RuntimeError("Streamlit readiness timeout")
finally:
    process.terminate()
    process.wait(timeout=10)
