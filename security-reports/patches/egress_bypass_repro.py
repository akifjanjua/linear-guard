#!/usr/bin/env python3
"""Does a stale _tls.approved_host let a module connect to an arbitrary IP?

Loopback only: connects to 127.0.0.1 on a closed port. ConnectionRefusedError
means the sandbox ALLOWED the call through to the real socket. SandboxViolation
means the gate blocked it. No external traffic, nothing persistent modified.
"""
import os, sys, socket, http.client

sys.path.insert(0, os.path.expanduser(r"~\.railcall\station\workbench"))
import module_sandbox as ms

SLUG = "test/egress-probe"
ns = {}
ms.install_restrictions(ns, {"network": ["api.linear.app"],
                             "subprocess": False,
                             "filesystem_writes": []}, slug=SLUG)

CLOSED = ("127.0.0.1", 9)   # discard port, closed here


def attempt(label):
    try:
        s = socket.socket()
        s.settimeout(1)
        s.connect(CLOSED)
        s.close()
        return f"{label}: CONNECT SUCCEEDED (gate allowed)"
    except ms.SandboxViolation as e:
        return f"{label}: BLOCKED by sandbox  <- gate held"
    except (ConnectionRefusedError, OSError) as e:
        return f"{label}: ALLOWED THROUGH to real socket ({type(e).__name__}) <- gate did NOT block"


with ms.sandbox_active(SLUG):
    # Control: no HTTP call yet, so nothing stashed on this thread.
    print(attempt("A. raw IP connect, no prior HTTP call "))

    # Legitimate, allowlisted HTTPConnection construction. __init__ does NOT
    # open a socket -- it only records host/port. This is what stashes
    # _tls.approved_host inside _wrapped_httpconn_init.
    http.client.HTTPConnection("api.linear.app")
    print("   (constructed HTTPConnection('api.linear.app') - no network yet)")

    # Same thread, after the stash.
    print(attempt("B. raw IP connect, AFTER allowlisted HTTPConnection"))
