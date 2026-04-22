from __future__ import annotations

import argparse
import threading
import time
import urllib.request
import webbrowser

import uvicorn


def _browser_host(host: str) -> str:
    if host in {"0.0.0.0", "::"}:
        return "127.0.0.1"
    return host


def _wait_for_server_and_open_browser(url: str, timeout_seconds: float = 15.0) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=0.5):
                webbrowser.open(url)
                return
        except Exception:
            time.sleep(0.2)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="transient",
        description="Run the transient web application.",
    )
    parser.add_argument("--host", default="127.0.0.1", help="Bind host. Default: 127.0.0.1")
    parser.add_argument("--port", type=int, default=8000, help="Bind port. Default: 8000")
    parser.add_argument(
        "--reload",
        action="store_true",
        help="Enable auto-reload for development.",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    url = f"http://{_browser_host(args.host)}:{args.port}"
    threading.Thread(
        target=_wait_for_server_and_open_browser,
        args=(url,),
        daemon=True,
    ).start()
    uvicorn.run("app.main:app", host=args.host, port=args.port, reload=args.reload)
