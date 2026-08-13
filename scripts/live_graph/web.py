"""Loopback-only static dashboard with selection-scoped state APIs."""

from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import ipaddress
import json
from pathlib import Path
import socket
import sys
import time
import threading
from typing import Any
from urllib.parse import parse_qs, urlencode, urlsplit
import webbrowser

from .sessions import SessionSelection, build_bundle


CONTENT_SECURITY_POLICY = (
    "default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
    "connect-src 'self'; font-src 'none'; object-src 'none'; base-uri 'none'; "
    "frame-ancestors 'none'; form-action 'none'"
)
ASSET_DIRECTORY = Path(__file__).with_name("assets")
INVALID_SELECTION = b"Invalid selection.\n"
MISSING_SELECTION = b"Selected session unavailable.\n"
STATE_UNAVAILABLE = b"Dashboard state unavailable.\n"
RECOVERABLE_STATE_READ_ERRORS = (OSError, TimeoutError, ValueError, TypeError, UnicodeError)


def _is_loopback(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _parse_selection(path: str) -> SessionSelection:
    """Accept precisely one safe, logical selection query."""
    query = urlsplit(path).query
    try:
        values = parse_qs(query, keep_blank_values=True, strict_parsing=True)
    except ValueError as error:
        raise ValueError("invalid selection") from error
    if set(values) == {"selection"} and values["selection"] == ["all"]:
        return SessionSelection.all()
    if set(values) == {"session"} and len(values["session"]) == 1:
        try:
            return SessionSelection.one(values["session"][0])
        except (TypeError, ValueError) as error:
            raise ValueError("invalid selection") from error
    raise ValueError("invalid selection")


def _selection_query(selection: SessionSelection) -> str:
    if selection.mode == "all" and selection.session_id is None:
        return urlencode({"selection": "all"})
    if selection.mode == "session" and selection.session_id is not None:
        return urlencode({"session": selection.session_id})
    raise ValueError("invalid session selection")


def make_handler(store: Any, selection: SessionSelection, stream_interval: float, keepalive_interval: float) -> type[BaseHTTPRequestHandler]:
    """Build fixed local routes around a store; handler input is never a file path."""
    del selection
    assets: dict[str, tuple[str, bytes]] = {
        "/": ("text/html; charset=utf-8", (ASSET_DIRECTORY / "index.html").read_bytes()),
        "/app.mjs": ("text/javascript; charset=utf-8", (ASSET_DIRECTORY / "app.mjs").read_bytes()),
        "/style.css": ("text/css; charset=utf-8", (ASSET_DIRECTORY / "style.css").read_bytes()),
    }

    class DashboardHandler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        server_version = "Claudex5Dashboard/1"
        sys_version = ""

        def _send(self, status: int, content_type: str, body: bytes) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Security-Policy", CONTENT_SECURITY_POLICY)
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.end_headers()
            self.wfile.write(body)

        def _trusted_host(self) -> bool:
            host_header = self.headers.get("Host", "")
            bound_host, bound_port = self.server.server_address[:2]
            allowed = {f"{bound_host}:{bound_port}", f"localhost:{bound_port}"}
            if ":" in str(bound_host):
                allowed.add(f"[{bound_host}]:{bound_port}")
            return host_header.lower() in {value.lower() for value in allowed}

        def _bundle(self, requested: SessionSelection) -> dict[str, object]:
            return build_bundle(store, requested, completed_limit=1)

        def _bundle_bytes(self, bundle: dict[str, object]) -> bytes:
            return json.dumps(bundle, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")

        def _stream_headers(self) -> None:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Security-Policy", CONTENT_SECURITY_POLICY)
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.end_headers()

        def _write_event(self, name: str, data: bytes) -> None:
            self.wfile.write(b"event: " + name.encode("ascii") + b"\n")
            self.wfile.write(b"data: " + data + b"\n\n")
            self.wfile.flush()

        def _write_keepalive(self) -> None:
            self.wfile.write(b": keepalive\n\n")
            self.wfile.flush()

        def _stream(self, requested: SessionSelection) -> None:
            """Write one initial bundle, then revisions only, until disconnect."""
            try:
                bundle = self._bundle(requested)
                encoded = self._bundle_bytes(bundle)
            except LookupError:
                self._send(404, "text/plain; charset=utf-8", MISSING_SELECTION)
                return
            except Exception:
                self._send(503, "text/plain; charset=utf-8", STATE_UNAVAILABLE)
                return
            try:
                revision = str(bundle["revision"])
                self._stream_headers()
                self._write_event("snapshot", encoded)
                degraded = False
                keepalive_at = time.monotonic() + keepalive_interval
                while not self.server.stop_event.wait(stream_interval):
                    try:
                        current = self._bundle(requested)
                        current_encoded = self._bundle_bytes(current)
                        current_revision = str(current["revision"])
                    except RECOVERABLE_STATE_READ_ERRORS:
                        if not degraded:
                            self._write_event("degraded", b'{"status":"degraded"}')
                            degraded = True
                    else:
                        if current_revision != revision:
                            self._write_event("snapshot", current_encoded)
                            revision = current_revision
                        degraded = False
                    if time.monotonic() >= keepalive_at:
                        self._write_keepalive()
                        keepalive_at = time.monotonic() + keepalive_interval
            except (BrokenPipeError, ConnectionResetError):
                return

        def do_GET(self) -> None:  # noqa: N802 - stdlib handler API
            if not self._trusted_host():
                self._send(403, "text/plain; charset=utf-8", b"Forbidden.\n")
                return
            split = urlsplit(self.path)
            if split.path == "/" and split.query:
                try:
                    _parse_selection(self.path)
                except ValueError:
                    self._send(400, "text/plain; charset=utf-8", INVALID_SELECTION)
                    return
            if split.path in assets and (not split.query or split.path == "/"):
                content_type, body = assets[split.path]
                self._send(200, content_type, body)
                return
            if split.path == "/api/snapshot":
                try:
                    selected = _parse_selection(self.path)
                except ValueError:
                    self._send(400, "text/plain; charset=utf-8", INVALID_SELECTION)
                    return
                try:
                    body = self._bundle_bytes(self._bundle(selected))
                except LookupError:
                    self._send(404, "text/plain; charset=utf-8", MISSING_SELECTION)
                    return
                except Exception:
                    self._send(503, "text/plain; charset=utf-8", STATE_UNAVAILABLE)
                    return
                self._send(200, "application/json; charset=utf-8", body)
                return
            if split.path == "/api/events":
                try:
                    selected = _parse_selection(self.path)
                except ValueError:
                    self._send(400, "text/plain; charset=utf-8", INVALID_SELECTION)
                    return
                self._stream(selected)
                return
            self._send(404, "text/plain; charset=utf-8", b"Not found.\n")

        def log_message(self, _format: str, *args: object) -> None:
            del args

    return DashboardHandler


class _DashboardServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self.stop_event = threading.Event()
        super().__init__(*args, **kwargs)

    def shutdown(self) -> None:
        self.stop_event.set()
        super().shutdown()

    def server_close(self) -> None:
        self.stop_event.set()
        super().server_close()

    def handle_error(self, _request: object, _client_address: object) -> None:
        sys.stderr.write("Dashboard request failed.\n")

class _IPv6DashboardServer(_DashboardServer):
    address_family = socket.AF_INET6


def create_server(
    store: Any,
    selection: SessionSelection,
    host: str = "127.0.0.1",
    port: int = 8765,
    stream_interval: float = 1.0,
    keepalive_interval: float = 15.0,
) -> ThreadingHTTPServer:
    """Bind the dashboard to loopback only with bounded polling settings."""
    if not isinstance(host, str) or not _is_loopback(host):
        raise ValueError("dashboard host must be a loopback address")
    if not isinstance(port, int) or isinstance(port, bool) or not 0 <= port <= 65535:
        raise ValueError("dashboard port must be between 0 and 65535")
    if not isinstance(selection, SessionSelection):
        raise ValueError("dashboard selection must be immutable")
    if not isinstance(stream_interval, (int, float)) or stream_interval <= 0:
        raise ValueError("stream interval must be positive")
    if not isinstance(keepalive_interval, (int, float)) or keepalive_interval <= 0:
        raise ValueError("keepalive interval must be positive")
    server_type = _IPv6DashboardServer if ":" in host else _DashboardServer
    return server_type((host, port), make_handler(store, selection, float(stream_interval), float(keepalive_interval)))


def serve_dashboard(
    store: Any,
    selection: SessionSelection,
    host: str = "127.0.0.1",
    port: int = 8765,
    open_browser: bool = False,
) -> int:
    """Serve the dashboard until interrupted, returning a conventional status."""
    server = create_server(store, selection, host, port)
    bound_host, bound_port = server.server_address[:2]
    display_host = f"[{bound_host}]" if ":" in str(bound_host) else bound_host
    url = f"http://{display_host}:{bound_port}/?{_selection_query(selection)}"
    print(f"Claudex5 dashboard: {url}", flush=True)
    if open_browser:
        try:
            webbrowser.open(url)
        except Exception:
            print("Browser launch failed; open the URL above manually.", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        return 0
    finally:
        server.server_close()
    return 0
