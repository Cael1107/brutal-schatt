#!/usr/bin/env python3
"""Lab mock target for Schatten toolchain self-test.
Exercises: /api/admin/login (NoSQL-style), /api/jwt (JWT issue), /api/race (idempotency),
/api/proxy-image (SSRF surface), / (browser page with reflected param).
Run: python3 lab_mock.py  --port 8899
"""
import sys, json, time, threading
from http.server import BaseHTTPRequestHandler, HTTPServer

class H(BaseHTTPRequestHandler):
    def _j(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.startswith("/api/articles"):
            return self._j({"articles": [{"id": 1, "title": "lab"}], "total": 1})
        if self.path.startswith("/api/proxy-image"):
            return self._j({"error": "proxy blocked in lab"}, 403)
        if self.path == "/api/admin/me":
            return self._j({"authed": False}, 401)
        if self.path == "/":
            q = self.path.split("?", 1)[1] if "?" in self.path else ""
            html = f"<html><body><h1>Lab</h1><p id='q'>{q}</p></body></html>"
            self.send_response(200); self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(html))); self.end_headers()
            self.wfile.write(html.encode()); return
        return self._j({"error": "not found"}, 404)

    def do_POST(self):
        ln = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(ln) if ln else b"{}"
        try:
            data = json.loads(raw or b"{}")
        except Exception:
            return self._j({"message": "invalid json"}, 400)
        if self.path == "/api/admin/login":
            # Simulate type-strict NoSQL (reject object values)
            if isinstance(data.get("username"), dict) or isinstance(data.get("password"), dict):
                return self._j({"message": "type error"}, 400)
            return self._j({"message": "Username atau password salah"}, 401)
        if self.path == "/api/jwt":
            return self._j({"token": "eyJhbGciOiJIUzI1NiJ9.eyJ1c2VyIjoiYWRtaW4ifQ.x"}, 200)
        if self.path == "/api/race":
            return self._j({"ok": True, "ts": time.time()}, 200)
        return self._j({"error": "not found"}, 404)

    def log_message(self, *a): pass

def main():
    port = int(sys.argv[sys.argv.index("--port") + 1]) if "--port" in sys.argv else 8899
    srv = HTTPServer(("127.0.0.1", port), H)
    print(f"LAB MOCK on http://127.0.0.1:{port}")
    srv.serve_forever()

if __name__ == "__main__":
    main()
