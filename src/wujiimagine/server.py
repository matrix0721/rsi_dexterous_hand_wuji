"""Loopback RPC; one serialized live-session owner, no motion retries."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hmac
import json
import secrets
import threading

from .context import METHODS
from .execution import write_json
from .skills import catalog


def serve(session, port=0):
    token = secrets.token_urlsafe(32)
    lock = threading.Lock()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            if not hmac.compare_digest(self.headers.get("Authorization", ""), "Bearer " + token):
                self.send_error(403)
                return
            if self.path != "/call":
                self.send_error(404)
                return
            try:
                length = int(self.headers.get("Content-Length", 0))
                if not 0 < length <= 16*1024*1024:
                    raise ValueError("request must be 1 byte to 16 MiB")
                payload = json.loads(self.rfile.read(length))
                method = payload["method"]
                if method not in METHODS:
                    raise ValueError("unknown tool")
                with lock:
                    result = getattr(session, method)(**payload.get("params", {}))
                body = json.dumps(result, ensure_ascii=False, allow_nan=False).encode()
                self.send_response(200)
            except Exception as exc:
                body = json.dumps({"error": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False).encode()
                self.send_response(400)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    descriptor = {"url": f"http://127.0.0.1:{server.server_port}", "token": token,
                  "backend": session.backend, "session_id": session.identity, "tools": list(METHODS)}
    path = session.output / "session.json"
    write_json(path, descriptor)
    core = [catalog(s["name"])["text"] for s in catalog()["skills"] if s.get("autoload")]
    (session.output / "agent_prompt.md").write_text(
        "# Wuji Imagine live session\n\n"
        f"Session descriptor: {path}\nBackend: {session.backend}\n\n"
        "Use wujiimagine.Context with this descriptor. Read ctx.skills() and load specialized\n"
        "skills as needed. Use current RGB-D and measured robot state; short blocks permit\n"
        "feedback. Thinking does not move the robot. Do not launch another hardware owner.\n"
        "A request timeout must not trigger automatic motion replay.\n\n"
        + "\n\n".join(core), encoding="utf-8")
    print(f"Session: {path}", flush=True)
    try:
        server.serve_forever(poll_interval=.2)
    finally:
        server.server_close()
