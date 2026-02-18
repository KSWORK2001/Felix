import argparse
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import List

import webview


ROOT_DIR = Path(__file__).resolve().parent.parent
FRONTEND_DIR = ROOT_DIR / "frontend" / "felix-front"


class OverlayApi:
    def __init__(self) -> None:
        self.window: webview.Window | None = None

    def bind_window(self, window: webview.Window) -> None:
        self.window = window

    def move_window(self, dx: int, dy: int) -> None:
        if self.window is None:
            return
        self.window.move(self.window.x + int(dx), self.window.y + int(dy))


def _is_port_open(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.4)
        return s.connect_ex((host, port)) == 0


def _wait_for_port(host: str, port: int, timeout_seconds: int = 120) -> bool:
    start = time.time()
    while time.time() - start < timeout_seconds:
        if _is_port_open(host, port):
            return True
        time.sleep(0.5)
    return False


def _start_services() -> List[subprocess.Popen]:
    children: List[subprocess.Popen] = []

    if not _is_port_open("127.0.0.1", 8000):
        api_proc = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "backend.main:app", "--host", "127.0.0.1", "--port", "8000"],
            cwd=str(ROOT_DIR),
        )
        children.append(api_proc)
        if not _wait_for_port("127.0.0.1", 8000):
            raise RuntimeError("Backend API did not start on http://127.0.0.1:8000")

    if not _is_port_open("127.0.0.1", 3000):
        npm_cmd = "npm.cmd" if os.name == "nt" else "npm"
        front_proc = subprocess.Popen(
            [npm_cmd, "run", "dev", "--", "--hostname", "127.0.0.1", "--port", "3000"],
            cwd=str(FRONTEND_DIR),
        )
        children.append(front_proc)
        if not _wait_for_port("127.0.0.1", 3000):
            raise RuntimeError("Next.js dev server did not start on http://127.0.0.1:3000")

    return children


def main() -> None:
    parser = argparse.ArgumentParser(description="Launch Felix desktop overlay with pywebview + Next.js")
    parser.add_argument("--spawn-services", action="store_true", help="Auto-start backend API and Next.js dev server")
    args = parser.parse_args()

    children: List[subprocess.Popen] = []
    if args.spawn_services:
        children = _start_services()

    frontend_url = os.environ.get("FELIX_FRONTEND_URL", "http://127.0.0.1:3000/overlay")

    api = OverlayApi()

    try:
        window = webview.create_window(
            title="Felix Overlay",
            url=frontend_url,
            width=520,
            height=700,
            frameless=True,
            transparent=True,
            easy_drag=True,
            on_top=True,
            js_api=api,
        )
        api.bind_window(window)

        webview.start(gui="edgechromium", debug=True)
    finally:
        for proc in children:
            if proc.poll() is None:
                proc.terminate()


if __name__ == "__main__":
    main()
