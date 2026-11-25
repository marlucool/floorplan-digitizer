"""Launch Planline in a native desktop window backed by its local API."""
from __future__ import annotations

import socket
import sys
import threading
import time


def _available_local_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


class DesktopBridge:
    """Small pywebview bridge for desktop-only actions."""

    def close_window(self) -> None:
        import webview
        if webview.windows:
            webview.windows[0].destroy()


def main() -> int:
    try:
        import webview
    except ImportError:
        print(
            "The desktop window dependency is missing. Install it with:\n"
            "  python -m pip install -r requirements-desktop.txt",
            file=sys.stderr,
        )
        return 2

    import uvicorn

    from .api import app

    port = _available_local_port()
    server = uvicorn.Server(
        uvicorn.Config(
            app,
            host="127.0.0.1",
            port=port,
            log_level="warning",
            access_log=False,
            lifespan="on",
        )
    )
    thread = threading.Thread(target=server.run, daemon=True, name="planline-local-api")
    thread.start()
    deadline = time.monotonic() + 20
    while not server.started and thread.is_alive() and time.monotonic() < deadline:
        time.sleep(0.1)
    if not server.started:
        server.should_exit = True
        thread.join(timeout=3)
        print("Planline's local API did not start. Check the Python installation.", file=sys.stderr)
        return 1

    try:
        webview.create_window(
            "Planline — Floor-plan and OCR Studio",
            f"http://127.0.0.1:{port}/",
            width=1500,
            height=980,
            min_size=(1024, 700),
            background_color="#fbfaf6",
            js_api=DesktopBridge(),
        )
        webview.start(debug=False)
    finally:
        server.should_exit = True
        thread.join(timeout=5)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
