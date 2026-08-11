#!/usr/bin/env python3
"""Regression: does the patched gate still allow LEGITIMATE allowlisted traffic?

Runs a throwaway HTTP server on loopback and drives real urllib + http.client
requests through the sandbox with 'localhost' allowlisted. No external traffic.

Usage: python regression_test.py <orig|fixed>
"""
import http.server, socketserver, sys, os, threading, urllib.request, http.client

which = sys.argv[1] if len(sys.argv) > 1 else "fixed"
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), which))
import module_sandbox as ms

class Quiet(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200); self.send_header("Content-Length", "2")
        self.end_headers(); self.wfile.write(b"ok")
    def log_message(self, *a): pass

srv = socketserver.TCPServer(("127.0.0.1", 0), Quiet)
port = srv.server_address[1]
threading.Thread(target=srv.serve_forever, daemon=True).start()

SLUG = "test/regress"
ms.install_restrictions({}, {"network": ["localhost"], "subprocess": False,
                             "filesystem_writes": []}, slug=SLUG)

results = []
with ms.sandbox_active(SLUG):
    # 1. urllib to an ALLOWLISTED host — must succeed.
    try:
        with urllib.request.urlopen(f"http://localhost:{port}/", timeout=3) as r:
            results.append(("urllib -> allowlisted host", r.read() == b"ok", ""))
    except Exception as e:
        results.append(("urllib -> allowlisted host", False, f"{type(e).__name__}: {e}"))

    # 2. Two sequential requests — the grant must re-arm each time, not be
    #    exhausted by the first (regression risk of the single-use change).
    try:
        ok = True
        for _ in range(3):
            with urllib.request.urlopen(f"http://localhost:{port}/", timeout=3) as r:
                ok = ok and r.read() == b"ok"
        results.append(("3 sequential allowlisted requests", ok, ""))
    except Exception as e:
        results.append(("3 sequential allowlisted requests", False, f"{type(e).__name__}: {e}"))

    # 3. Raw http.client to allowlisted host — must succeed.
    try:
        conn = http.client.HTTPConnection("localhost", port, timeout=3)
        conn.request("GET", "/")
        body = conn.getresponse().read()
        conn.close()
        results.append(("http.client -> allowlisted host", body == b"ok", ""))
    except Exception as e:
        results.append(("http.client -> allowlisted host", False, f"{type(e).__name__}: {e}"))

    # 4. NON-allowlisted host — must still be refused.
    try:
        urllib.request.urlopen("http://evil.example/", timeout=3)
        results.append(("urllib -> non-allowlisted host REFUSED", False, "was allowed!"))
    except ms.SandboxViolation:
        results.append(("urllib -> non-allowlisted host REFUSED", True, ""))
    except Exception as e:
        results.append(("urllib -> non-allowlisted host REFUSED", False, f"{type(e).__name__}"))

srv.shutdown()
print(f"=== {which} ===")
for name, ok, detail in results:
    print(f"  [{'PASS' if ok else 'FAIL'}] {name} {detail}")
