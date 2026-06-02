from __future__ import annotations

import http.server
import socketserver
from pathlib import Path

PORT = 8501
WEB_ROOT = Path(__file__).resolve().parent


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(WEB_ROOT), **kwargs)


def main() -> None:
    with socketserver.TCPServer(("0.0.0.0", PORT), Handler) as httpd:
        print(f"Serving dashboard on http://0.0.0.0:{PORT}")
        httpd.serve_forever()


if __name__ == "__main__":
    main()
