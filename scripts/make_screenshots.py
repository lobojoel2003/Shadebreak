"""Regenerate every README image in one go.

    python scripts/make_screenshots.py

Starts the pinned-clock demo server, captures screenshots with Playwright
(Node), renders the sample heat plan and composes the final images.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PORT = 8765
BASE = f"http://127.0.0.1:{PORT}"


def wait_for_server(timeout: float = 60) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(f"{BASE}/healthz", timeout=2):  # noqa: S310 - local URL
                return
        except OSError:
            time.sleep(0.5)
    sys.exit("Demo server did not start")


def main() -> None:
    images = ROOT / "docs" / "images"
    dist = ROOT / "dist"
    server = subprocess.Popen([sys.executable, str(ROOT / "scripts" / "demo_server.py"), "--port", str(PORT)])
    try:
        wait_for_server()
        subprocess.run(["node", str(ROOT / "scripts" / "screenshots.cjs"), BASE, str(images)], check=True, env=os.environ)
    finally:
        server.terminate()
        server.wait(timeout=10)
    subprocess.run([sys.executable, str(ROOT / "scripts" / "sample_plan.py"), "--out", str(dist)], check=True)
    subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "compose_images.py"), str(images), str(dist / "shadebreak-sample-heat-plan-en.pdf")],
        check=True,
    )


if __name__ == "__main__":
    main()
