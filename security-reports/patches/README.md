# Proposed patches for RailCall platform findings

Two proposed fixes against **station-v0.78**, for private disclosure to Sami.
Nothing here is applied to the live install — these are diffs plus the scripts
that reproduce the bug and prove the fix.

`security-reports/` is listed in `.moduleignore`, so nothing in this directory
enters the signed module tree. Adding that one line did change `.moduleignore`
itself, which **is** signed, so the module was re-signed once when this landed.

| file | what it is |
|---|---|
| `module_sandbox.egress-grant-scope.patch` | fix for the egress allowlist bypass |
| `railcall_cli.publish-newline.patch` | fix for publish-side CR→LF corruption |
| `egress_bypass_repro.py` | reproduces the bypass (loopback only) |
| `egress_regression_test.py` | proves the fix keeps legitimate traffic working |

Apply with `patch -p1` from the workbench root, or read them as-is.

---

## 1. `module_sandbox.egress-grant-scope.patch`

**Bug.** A module declaring `requires.network: ["api.linear.app"]` can reach
**any host by IP**. `_wrapped_httpconn_init` set `_tls.approved_host` and never
cleared it — unlike `_wrapped_urlopen`, which clears in a `finally`. Because
`HTTPConnection.__init__` opens no socket, merely *constructing* an allowlisted
connection armed the thread permanently; `_wrapped_socket_connect` then
re-checked the stashed **name** rather than the address being dialled, so every
later raw-IP `connect()` on that thread passed.

**Fix.** Three parts:

1. `__init__` records the approved name on the **connection instance**
   (`self._rc_approved_host`) instead of arming the thread.
2. A new `HTTPConnection.connect` wrapper arms `_tls.approved_host` only for the
   dynamic extent of the real connect, in a `try/finally`. That is the only
   window where a raw-IP connect is authorised, and it correctly spans the
   several `connect()` calls `create_connection` makes when a host resolves to
   both A and AAAA records.
3. `_addr_belongs_to()` confirms the dialled address is actually one the
   approved hostname resolves to. It fails **open** when resolution itself fails
   (offline boxes) and **closed** when resolution succeeds but the address is
   absent — the DNS-rebinding case.

Also folded in: `_hostname_of` now uses `urllib.parse` instead of hand-splitting.
The hand-rolled version disagreed with the parser urllib actually dials with:

| URL | old result | real host |
|---|---|---|
| `https://api.linear.app:@evil.example/` | `api.linear.app` (allowed) | `evil.example` |
| `https://user:pass@api.linear.app/` | `user` (refused) | `api.linear.app` |

The first was not independently exploitable — the `HTTPConnection` layer
re-checks with the real host — but it made the first layer wrong. The second
false-blocked a legitimate basic-auth URL.

**Verified.**

```
EXPLOIT                                    orig                      fixed
  A. raw IP, no prior HTTP call            BLOCKED                   BLOCKED
  B. raw IP, AFTER allowlisted HTTPConn    ALLOWED THROUGH           BLOCKED

REGRESSION (fixed)
  [PASS] urllib -> allowlisted host
  [PASS] 3 sequential allowlisted requests
  [PASS] http.client -> allowlisted host
  [PASS] urllib -> non-allowlisted host REFUSED
```

**Note on scope.** This closes the demonstrated hole. It does **not** change the
limitations `module_sandbox.py` already documents honestly (ctypes, `_socket`
under the wrap, unrestricted reads) — those remain Phase 5 work.

---

## 2. `railcall_cli.publish-newline.patch`

**Bug.** `railcall market publish` reads the canonical files in text mode with
default `newline=None`, i.e. universal newlines, which rewrites `\r\n` *and*
lone `\r` to `\n`. A CR-only `handlers/handler.py` was uploaded LF-only in
`payload["handler_py"]`. Install writes that payload verbatim (v0.77+ correctly
uses `newline=""`), so the buyer's tree hash mismatched and the module was
rejected as *"files edited after sign"*.

Publish's own signature self-check still passed, because the tarball and
`tree_manifest` come from `_module_tree_walk`, which opens `"rb"`. Only the
redundant payload string was corrupt — which is why the Marketplace reports the
listing as signature-valid while every install is rejected.

**Fix.** `newline=""` on both canonical reads.

**Verified** against this repo's real `handlers/handler.py`:

```
signed bytes on disk        :  109884 bytes LF=   0 CR=3310 fc4da51ad660
current  (newline default)  :  109884 bytes LF=3310 CR=   0 034a5243a754   matches signed: False
patched  (newline="")       :  109884 bytes LF=   0 CR=3310 fc4da51ad660   matches signed: True
```

**Deployment note.** Fixing publish does not repair listings already uploaded —
the corrupted `handler_py` is stored server-side, so affected modules must be
republished after the fix ships.
