# -*- coding: utf-8 -*-
"""Share generated worship HTML to iPad / iPhone on the same Wi‑Fi."""

from __future__ import annotations

import io
import socket
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent
OUTPUT_DIR = ROOT / "output"
DEFAULT_PORT = 8765

_lock = threading.Lock()
_server: ThreadingHTTPServer | None = None
_thread: threading.Thread | None = None
_port: int = DEFAULT_PORT


def lan_ip() -> str:
    """Best-effort LAN IPv4 for phones on the same Wi‑Fi."""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(0.4)
        sock.connect(("8.8.8.8", 80))
        ip = sock.getsockname()[0]
        sock.close()
        if ip and not ip.startswith("127."):
            return ip
    except OSError:
        pass
    try:
        return socket.gethostbyname(socket.gethostname())
    except OSError:
        return "127.0.0.1"


def share_url(filename: str = "worship_live.html", *, port: int | None = None) -> str:
    p = int(port or _port or DEFAULT_PORT)
    # present=1 → iPad/iPhone opens worship slides instead of the desktop editor UI
    return f"http://{lan_ip()}:{p}/{filename.lstrip('/')}?present=1"


def is_running() -> bool:
    with _lock:
        return _server is not None


def stop_share_server() -> None:
    global _server, _thread
    with _lock:
        srv = _server
        _server = None
        _thread = None
    if srv is not None:
        try:
            srv.shutdown()
        except Exception:
            pass
        try:
            srv.server_close()
        except Exception:
            pass


def start_share_server(
    directory: Path | None = None,
    *,
    port: int = DEFAULT_PORT,
) -> dict:
    """
    Serve the output folder so iPad/iPhone can open worship_live.html.
    Returns {ok, url, port, ip, path, message}.
    """
    global _server, _thread, _port

    out = Path(directory or OUTPUT_DIR).resolve()
    out.mkdir(parents=True, exist_ok=True)
    live = out / "worship_live.html"
    if not live.is_file():
        return {
            "ok": False,
            "url": "",
            "port": port,
            "ip": lan_ip(),
            "path": str(live),
            "message": "예배화면 HTML이 아직 없습니다. 먼저 생성해 주세요.",
        }

    with _lock:
        if _server is not None and _port == port:
            return {
                "ok": True,
                "url": share_url(port=port),
                "port": port,
                "ip": lan_ip(),
                "path": str(live),
                "message": "이미 공유 중입니다. 같은 Wi‑Fi에서 아래 주소/QR로 여세요.",
            }
        # Restart on different port / fresh bind
        old = _server
        _server = None
        _thread = None

    if old is not None:
        try:
            old.shutdown()
            old.server_close()
        except Exception:
            pass

    handler = partial(_QuietHandler, directory=str(out))
    last_err: Exception | None = None
    chosen = port
    httpd: ThreadingHTTPServer | None = None
    for candidate in (port, port + 1, port + 2, 0):
        try:
            httpd = ThreadingHTTPServer(("0.0.0.0", candidate), handler)
            chosen = httpd.server_address[1]
            break
        except OSError as exc:
            last_err = exc
            httpd = None
    if httpd is None:
        return {
            "ok": False,
            "url": "",
            "port": port,
            "ip": lan_ip(),
            "path": str(live),
            "message": f"공유 서버를 열 수 없습니다: {last_err}",
        }

    thread = threading.Thread(target=httpd.serve_forever, name="worship-html-share", daemon=True)
    with _lock:
        _server = httpd
        _thread = thread
        _port = chosen
    thread.start()

    url = share_url(port=chosen)
    return {
        "ok": True,
        "url": url,
        "port": chosen,
        "ip": lan_ip(),
        "path": str(live),
        "message": "같은 Wi‑Fi의 iPad/iPhone Safari에서 주소 또는 QR로 여세요.",
    }


class _QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args) -> None:  # noqa: A003
        return

    def end_headers(self) -> None:
        # Helpful for mobile Safari caching during rehearsal updates
        self.send_header("Cache-Control", "no-store, max-age=0")
        self.send_header("Access-Control-Allow-Origin", "*")
        super().end_headers()


def qr_png_bytes(url: str, *, box_size: int = 8) -> Optional[bytes]:
    """PNG bytes for a QR code, or None if qrcode is unavailable."""
    try:
        import qrcode
    except ImportError:
        return None
    img = qrcode.make(url, box_size=box_size, border=2)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def ensure_live_file(html_bytes: bytes, path: Path | None = None) -> Path:
    live = Path(path or (OUTPUT_DIR / "worship_live.html"))
    live.parent.mkdir(parents=True, exist_ok=True)
    live.write_bytes(html_bytes)
    return live
