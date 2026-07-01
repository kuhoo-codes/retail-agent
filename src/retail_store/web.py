from __future__ import annotations

import argparse
import json
import os
import sqlite3
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from retail_store.agent import RetailAgent
from retail_store.cli import HELP, WELCOME, ensure_database
from retail_store.config import (
    DEFAULT_DATABASE_PATH,
    DEFAULT_DATA_DIR,
    PROJECT_ROOT,
    load_dotenv,
)
from retail_store.database import connect
from retail_store.seed import seed_database


STATIC_DIR = PROJECT_ROOT / "src" / "retail_store" / "web_static"
CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
}


class WebSession:
    """Stateful adapter that gives the browser the same behavior as the CLI."""

    def __init__(
        self,
        database_path: Path = DEFAULT_DATABASE_PATH,
        data_dir: Path = DEFAULT_DATA_DIR,
    ) -> None:
        self.database_path = database_path
        self.data_dir = data_dir
        self._lock = threading.RLock()
        ensure_database(data_dir, database_path)
        self.connection = connect(database_path)
        self.agent = RetailAgent(self.connection)

    def close(self) -> None:
        with self._lock:
            self.connection.close()

    def execute(self, text: str) -> dict[str, Any]:
        if not isinstance(text, str):
            return {"ok": False, "output": "Prompt must be text."}
        command = text.strip()
        if not command:
            return {"ok": False, "output": "Please enter a retail instruction."}
        with self._lock:
            if command.casefold() == "help":
                return {"ok": True, "output": HELP}
            if command.casefold() in {"exit", "quit"}:
                return {
                    "ok": True,
                    "output": "Goodbye.",
                    "exit": True,
                }
            if command.casefold() == "reset":
                return self.reset()
            try:
                return {
                    "ok": True,
                    "output": self.agent.handle_user_message(command),
                }
            except sqlite3.Error as exc:
                if os.getenv("DEBUG") == "1":
                    raise
                return {"ok": False, "output": f"Database error: {exc}"}

    def reset(self) -> dict[str, Any]:
        with self._lock:
            self.connection.close()
            try:
                seed_database(self.data_dir, self.database_path)
                self.connection = connect(self.database_path)
                self.agent = RetailAgent(self.connection)
            except Exception:
                if os.getenv("DEBUG") == "1":
                    raise
                return {
                    "ok": False,
                    "output": "Unable to reset the store database.",
                }
            return {"ok": True, "output": "Store data and session memory reset."}


def create_handler(session: WebSession) -> type[BaseHTTPRequestHandler]:
    class RetailWebHandler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: object) -> None:
            if os.getenv("DEBUG") == "1":
                super().log_message(format, *args)

        def _send_json(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
            body = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self) -> None:
            if urlparse(self.path).path != "/api/prompt":
                self._send_json(HTTPStatus.NOT_FOUND, {"error": "not found"})
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if length > 64_000:
                    raise ValueError("request is too large")
                payload = json.loads(self.rfile.read(length).decode("utf-8"))
                prompt = payload["prompt"]
            except (ValueError, UnicodeDecodeError, json.JSONDecodeError, KeyError):
                self._send_json(
                    HTTPStatus.BAD_REQUEST,
                    {"ok": False, "output": "Invalid prompt request."},
                )
                return
            result = session.execute(prompt)
            self._send_json(HTTPStatus.OK, result)

        def do_GET(self) -> None:
            path = urlparse(self.path).path
            relative = {
                "/": "index.html",
                "/index.html": "index.html",
                "/terminal.css": "terminal.css",
                "/terminal.js": "terminal.js",
            }.get(path)
            if relative is None:
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            file_path = STATIC_DIR / relative
            try:
                body = file_path.read_bytes()
            except OSError:
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            self.send_response(HTTPStatus.OK)
            self.send_header(
                "Content-Type",
                CONTENT_TYPES.get(file_path.suffix, "application/octet-stream"),
            )
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return RetailWebHandler


def run_web(host: str = "127.0.0.1", port: int = 8000) -> None:
    load_dotenv()
    session = WebSession()
    server = HTTPServer((host, port), create_handler(session))
    print(f"{WELCOME}")
    print(f"Web terminal: http://{host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nGoodbye.")
    finally:
        server.server_close()
        session.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Retail Store Agent web terminal")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    arguments = parser.parse_args()
    run_web(arguments.host, arguments.port)


if __name__ == "__main__":
    main()
