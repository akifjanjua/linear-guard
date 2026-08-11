# RailCall platform — private security disclosure

**To:** Sami (RailCall)
**From:** Muhammad Akif Janjua (publisher, `muhammad-akif-janjua/linear-guard`)
**Date:** 2026-08-12
**Platform audited:** station-v0.78 (Windows install; `railcall_cli.py` sha256 `aca25c90963b…`)
**Handling:** Please treat as confidential until fixed. This document contains
working reproduction code for unpatched issues. It has deliberately not been
posted to the community forum, pushed to any remote, or included in my module's
signed tree.

---

## Summary

Six findings. Two ship with tested patches. The first two compose into a single
attack that defeats both halves of the product's core promise — the approval
airlock and declared egress — so I've led with the composition rather than the
parts.

| # | Finding | Severity | Patch |
|---|---|---|---|
| 1 | `/api/commands/{preview,approve,execute}` require no session token | High | suggested |
| 2 | Module network allowlist steppable via stale connect grant | High | **attached** |
| 3 | Publisher-trust allowlist defaults off and is not tamper-evident | High | suggested |
| 4 | `railcall verify` doesn't bind a receipt's signature to its body | High | suggested |
| 5 | Policy bundles can loosen, contradicting the stated guarantee | Medium | suggested |
| 6 | `publish` corrupts CR-only `handler.py` via universal newlines | Medium | **attached** |

Method throughout: read the source, then reproduce. Every claim below is marked
**Observed** (I ran it, output included) or **Inferred** (reasoned from code I
read, not executed). Nothing in the live install was modified — patches were
authored and tested against scratchpad copies, and both platform files are
byte-identical to their pre-audit snapshots.

---

## 0. The composed risk — lead with this

Findings 1 and 2 are individually serious. Together they remove the airlock and
the egress boundary in one motion.

**The chain.** Any local process — a malicious `postinstall`, a rogue dev tool, a
compromised editor extension, anything running as the operator — can:

1. `POST /api/commands/preview` → `approve` → `execute` against the loopback
   Studio API **with no session token**, supplying only an `Origin` header any
   non-browser client can set (Finding 1). The human never clicks anything.
2. Have that execution run a module whose declared `requires.network` allowlist
   does not actually confine it, because one allowlisted `HTTPConnection`
   permanently arms the thread for raw-IP connects (Finding 2).

**Net effect:** an unauthenticated local caller drives a real governed write, and
the code executing that write can reach a host the manifest never declared. Both
of the guarantees the marketplace makes on publishers' behalf — *"every external
write goes through the airlock"* and *"this module only talks to what it
declared"* — are bypassed without touching a signing key, a credential, or the
publisher-trust list.

**Why it isn't mitigated by loopback-only binding.** The session token exists
precisely to distinguish the Studio UI from other local processes —
`studio_server.py:6530` says so directly: *"the token is embedded in the pages
Studio serves, so a same-origin UI fetch carries it while a blind local caller
does not -> 403."* On the execute path that distinction currently isn't made.

**Inferred, not tested:** I verified the auth boundary with a deliberately
non-existent command id so nothing real would fire, and I did not chain the two
against a live provider. The composition is read from the code paths, not
demonstrated end to end.

---

## 1. Studio: preview/approve/execute accept unauthenticated POSTs

**Severity: High.** Bypasses the human-in-the-loop gate for governed writes.

### Observed

`_require_session()` is per-route opt-in — 74 call sites across the route
modules, no middleware. In `routes/dispatch_cap_off_wave3.py`, the route
immediately above the command quartet enforces it:

```python
    if (
        path == "/api/flow/automap"
    ):
        if not handler._require_session():      # line 754
            return True
```

The four routes below it do not. Lines 800–852 go straight to the handler:

```python
    if (
        path == "/api/commands/execute"
    ):  # governed execute — writes require a matching approval, every path -> receipt
        handler._send(
            200,
            {
                "ok": True,
                "receipt": execute_command(
                    body.get("command_id"),
                    body.get("inputs", {}),
                    body.get("intent", ""),
                ),
            },
        )
```

Each `if path ==` block is independent; there is no enclosing session check.

Reproduced with a non-existent command id (nothing real could execute):

```
NO session token, Origin header only:
  /api/modules/reload          -> HTTP 403  SESSION ENFORCED
  /api/commands/validate       -> HTTP 200  ACCEPTED - no session required
  /api/commands/preview        -> HTTP 200  ACCEPTED - no session required
  /api/commands/approve        -> HTTP 200  ACCEPTED - no session required
  /api/commands/execute        -> HTTP 200  ACCEPTED - no session required
```

Reloading a module is protected. Approving and executing a governed write is not.

### Inferred

`_guard()` still enforces a loopback `Host` and a loopback `Origin`/`Referer` on
POST, which stops a browser-driven CSRF from a remote page. It does not stop a
local non-browser client, which sets those headers freely — I did. That is
exactly the caller `_require_session` was written to exclude.

I did not test with a real command id, because that would fire an actual
external write.

### Suggested fix

Add the standard two lines to each of the four routes:

```python
        if not handler._require_session():
            return True
```

Given this is per-route opt-in with 74 call sites, it may be worth inverting the
default — an explicit allowlist of session-exempt paths, so a newly added route
fails closed rather than open. That would have caught this one.

---

## 2. Module network allowlist steppable via stale connect grant

**Severity: High.** Defeats `requires.network`, the mechanism modules use to make
an egress claim. **Patch attached:** `patches/module_sandbox.egress-grant-scope.patch`

### Observed

In `module_sandbox.py`, `_wrapped_urlopen` clears its threadlocal stash in a
`finally`:

```python
        finally:
            _tls.approved_host = None
```

`_wrapped_httpconn_init` sets the same stash and never clears it:

```python
        _check(host, "http.client.HTTPConnection", cur_slug, cur_allow)
        _tls.approved_host = _hostname_of(host)
        return _real_httpconn_init(self, host, *args, **kwargs)
```

`_wrapped_socket_connect` then treats that stashed **name** as authorisation for
any IP literal:

```python
                if _is_ip_literal(host):
                    approved = getattr(_tls, "approved_host", None)
                    if approved:
                        _check(approved, "socket.connect(resolved from " + approved + ")",
                               cur_slug, cur_allow)
```

Reproduced (`patches/egress_bypass_repro.py`, loopback only), with the module
declaring `requires.network: ["api.linear.app"]`:

```
A. raw IP connect, no prior HTTP call : BLOCKED by sandbox  <- gate held
   (constructed HTTPConnection('api.linear.app') - no network yet)
B. raw IP connect, AFTER allowlisted HTTPConnection: ALLOWED THROUGH to real socket
```

The control blocks correctly. Then **merely constructing** `HTTPConnection` —
`__init__` opens no socket and sends nothing — permanently arms that thread, and
a raw `socket.socket().connect((any_ip, port))` passes.

### Why this is distinct from the documented limitations

`module_sandbox.py:35–48` honestly lists known bypasses — `ctypes`, `_socket`
beneath the wrap, unrestricted reads. This one uses the **patched**
`socket.socket.connect`: the wrap fires and approves. It is a logic flaw in the
gate, not a gap the module admits to.

### Also fixed in the same patch: `_hostname_of` parser divergence

`_hostname_of` hand-splits URLs and disagrees with the parser urllib actually
dials with:

| URL | `_hostname_of` | real host | effect |
|---|---|---|---|
| `https://api.linear.app:@evil.example/` | `api.linear.app` | `evil.example` | first layer allows |
| `https://user:pass@api.linear.app/` | `user` | `api.linear.app` | false-blocks a legitimate URL |

The first is **not independently exploitable** — the `HTTPConnection` layer
re-checks with the real host, so defence in depth holds. It still means the
outer layer is wrong. The second is a plain reliability bug.

### The patch

Three parts, all in `module_sandbox.py`:

1. `__init__` records the approved name on the **connection instance**
   (`self._rc_approved_host`) rather than arming the thread.
2. A new `HTTPConnection.connect` wrapper arms `_tls.approved_host` only for the
   dynamic extent of the real connect, in a `try/finally`.
3. `_addr_belongs_to()` confirms the dialled address actually resolves from the
   approved host — fails **open** when resolution fails (offline boxes), **closed**
   when it succeeds and the address is absent.

Plus `_hostname_of` rewritten onto `urllib.parse`.

**A note on the design, because I got it wrong first.** My initial patch made the
grant single-use *per connect*. That broke legitimate traffic: `localhost`
resolves to both `::1` and `127.0.0.1`, and `create_connection` tries each in
turn, so the first failed attempt consumed the grant. The correct scope is one
*connection*, not one *connect* — hence the `connect`-wrapper approach. The
regression test (`patches/egress_regression_test.py`) exists because of that
mistake and is worth keeping.

Verified:

```
EXPLOIT                                    orig                fixed
  A. raw IP, no prior HTTP call            BLOCKED             BLOCKED
  B. raw IP, AFTER allowlisted HTTPConn    ALLOWED THROUGH     BLOCKED

REGRESSION (fixed)
  [PASS] urllib -> allowlisted host
  [PASS] 3 sequential allowlisted requests
  [PASS] http.client -> allowlisted host
  [PASS] urllib -> non-allowlisted host REFUSED
```

This closes the demonstrated hole. It does not change the Phase 5 limitations the
file already documents.

---

## 3. Publisher-trust allowlist: off by default, and not tamper-evident

**Severity: High.** This is the trust root for *which code runs at all*.

### Observed

`trust_mode: "any"` is the shipped default (`publisher_trust.py:16`) — *"load
every valid signature."* On my install the file is **absent entirely**, which
resolves the same way:

```
publisher_trust.json ABSENT -> defaults to trust_mode=any (load every valid signature)
```

The store carries no integrity protection — plain JSON written atomically at
0600 (`os.open(..., 0o600)` line 87, `os.chmod` line 97). No signature, no HMAC,
no hash chain, no receipt.

### Inferred

Two consequences.

**The layering assumes it's on.** `module_sandbox.py:43` states: *"The
publisher-trust allowlist is the primary defense; this layer is 'declared
capabilities + fail-loud on violation.'"* Finding 2 is a hole in the secondary
layer — but on a default install the primary layer isn't engaged either, so
there is nothing behind it.

**It's the one unauthenticated trust artefact.** Receipts are Ed25519-signed, the
team manifest is root-signed, policy bundles are root-signed. The file that
decides which publishers may register commands is protected by filesystem
permissions alone. Anything running as the operator can add a publisher key or
flip the mode, and nothing detects or records it — no receipt, no audit line, no
version counter.

### Suggested fix

Two independent changes. Sign the trust file with the install key and verify on
read, the way `current_bundle()` re-verifies the policy bundle — so a hand-edit
is detectable rather than silent. Separately, consider whether `any` is the right
default now that the marketplace has third-party publishers; if it must stay for
compatibility, the Modules tab could surface "publisher trust: OFF" as a visible
posture rather than a silent one.

---

## 4. `railcall verify` doesn't bind a receipt's signature to its body

**Severity: High.** Receipts are the platform's core evidentiary artefact, and
this is the tool marketed for third-party offline audit.

### Observed

The signature covers only the integrity-field **string**
(`railcall_cli.py:2312`):

```python
            pk.verify(bytes.fromhex(sb.get("sig", "")), str(ih).encode("utf-8"))
```

A body recompute exists and the code explains exactly why:

> *"Verifying only the signature would pass a receipt whose BODY was edited but
> whose hash field left stale — so recompute the hash from the body first."*

But it's gated behind two schema checks — `railcall_workflow_dagrun_receipt`
(line 2236) and `railcall_agent_receipt` (line 2257). Every other schema skips it.

Reproduced: I copied a real receipt, changed `result_status` from
`not_configured` to `executed`, added a fabricated `output`, and left
`integrity_hash` and `signature` byte-identical.

```
=========== TAMPERED receipt (body edited, hash+sig untouched) ===========
│ ✓ SIGNATURE VALID   the integrity_hash field is signed by this install's key │
```

The Studio auditor catches the same file — `audit_command_receipt` makes
`integrity_hash recomputes` its **first** check, and it FAILs while the signature
check still passes. So the two verifiers disagree about identical bytes.

Scope, measured across my install — **189 of 189 signed receipts** are in the
skip bucket. The two schemas the CLI does recompute do not appear at all:

```
   158  railcall_command_receipt.v1     ih=integrity_hash  CLI-SKIPS-recompute
     8  railcall_credential_receipt.v0  ih=integrity       CLI-SKIPS-recompute
     8  railcall_composed_dryrun.v0     ih=integrity       CLI-SKIPS-recompute
     6  railcall_workflow_receipt.v1    ih=integrity_root  CLI-SKIPS-recompute
     3  railcall_build_receipt.v0       ih=integrity_hash  CLI-SKIPS-recompute
     3  railcall_rail_save.v0           ih=integrity       CLI-SKIPS-recompute
     2  railcall_sheet_send.v0          ih=integrity       CLI-SKIPS-recompute
     1  railcall_workflow_staged.v1     ih=integrity       CLI-SKIPS-recompute
```

### Inferred

This is **not** forgery — minting a fresh valid signature still requires the
install key. It is a verification gap: an auditor handed a receipt file is told
the record is authentic while its narrative has been rewritten. Given `railcall
verify --key` is offered specifically to third parties who have nothing but the
file, that's the exact population this misleads.

### Suggested fix

Generalise the recompute instead of enumerating schemas — for any receipt
carrying an integrity field, recompute over the body and fail on mismatch before
reporting on the signature. The per-schema `startswith` list is the bug class
that produced this; the same reasoning appears in `approval_airlock._integrity`,
which deliberately inverted its allowlist to a denylist so *"a field added later
is covered by default."* The verifier deserves the same inversion.

---

## 5. Policy bundles can loosen, contradicting the stated guarantee

**Severity: Medium** (bounded by possession of the offline team root seed).

### Observed

`team_policy.py:12` states the guarantee:

> *"A bundle may only ADD control, never remove it."*

and line 17: *"a remote document must never be able to switch a laptop's
protections off."*

Adoption is a wholesale replace (lines 189–192):

```python
    applied = dict(doc["requires_team_approval"])
    applied["_bundle"] = {"version": doc["version"], "team_id": doc["team_id"],
                          "adopted_at": _now_iso()}
    _jwrite(_applied_path(ws), applied)
```

There is no comparison against the currently-applied map. Version monotonicity
(line 183) blocks *replay* of an older bundle but not a *forward* bundle
containing less.

Demonstrated with a throwaway root key — both bundles verify:

```
v2 (tightened)   verify_bundle -> True (ok)
                 applied map providers      = {'stripe': {'role': 'approver', 'quorum': 2}}
v3 (emptied)     verify_bundle -> True (ok)
                 applied map providers      = {}
```

v3 > v2, so monotonicity passes and the co-sign requirements are erased on every
station that adopts it.

### Inferred

The actor must hold the team root seed, so this is not a Relay-forgery path — the
Relay genuinely cannot forge. But the claim is about the *mechanism*, and the
mechanism does let a signed remote document switch protections off silently, with
no member consent and no local override. Membership changes are visible in the
roster; a policy loosening is invisible unless someone reads
`approval_policy.json`.

Worth noting the docstring already contains the correct instinct for
hypothetical future fields — *"adoption must enforce monotone tightening
per-field, not trust the sender"* — and simply doesn't apply it to the one field
that exists today, which loosens by omission.

### Suggested fix

Make adoption a monotone merge rather than a replace: for each
provider/action_class, keep the stricter of {currently applied, incoming}, and
refuse (or require explicit local confirmation) when a bundle drops an entry or
lowers a quorum. That makes the docstring true rather than aspirational.

---

## 6. `publish` corrupts CR-only `handler.py` via universal newlines

**Severity: Medium.** Silently breaks installs for any publisher whose source
isn't LF. **Patch attached:** `patches/railcall_cli.publish-newline.patch`

### Observed

`railcall_cli.py:5577`:

```python
        with open(handler_path, "r", encoding="utf-8") as f:
            handler_text = f.read()
```

Text mode defaults to `newline=None` — universal newlines — which collapses
`\r\n`, lone `\r`, and `\n` all to `\n`. A CR-only `handlers/handler.py` becomes
LF-only in `payload["handler_py"]` (line 5647) and ships that way.

At install, the tarball extracts correctly in binary, and is then **overwritten**
from the payload string (lines 4274–4283, "Always overwrite the three canonical
files from payload strings"). Since v0.77 that write correctly uses
`newline=""`, so it faithfully writes the already-corrupted LF bytes. The buyer's
tree hash mismatches and Studio rejects the module as *"files edited after
sign."*

Simulating that exact read on my repo's handler reproduces the installed file
byte-for-byte:

```
repo on disk (binary)      : 109884 bytes  LF=0 CR=3310 fc4da51ad660
after publish text-read    : 109884 bytes  LF=3310 CR=0 034a5243a754
installed copy on disk     : 109884 bytes  LF=3310 CR=0 034a5243a754
simulation == installed copy : True
```

**Why the Marketplace still reports the listing signature-valid:** publish's own
check signs `canonical(manifest) + \n + tree_manifest`, and the tree manifest
comes from `_module_tree_walk`, which opens `"rb"`. The tarball is correct too.
Only the redundant `handler_py` payload string is corrupt — so the listing looks
healthy while every install fails.

### The patch

`newline=""` on both canonical reads. Verified: the patched read reproduces the
signed bytes exactly (`fc4da51ad660`).

### Deployment note

Fixing publish does not repair listings already uploaded — the corrupted
`handler_py` is stored server-side. Affected modules must be republished after
the fix ships. Until then the workaround is a post-install file replacement,
which does not survive `--force` reinstall.

---

## Attachments

All under `security-reports/patches/`:

| file | purpose |
|---|---|
| `module_sandbox.egress-grant-scope.patch` | Finding 2 fix — apply with `patch -p1` from the workbench root |
| `railcall_cli.publish-newline.patch` | Finding 6 fix |
| `egress_bypass_repro.py` | reproduces Finding 2 (loopback only, no external traffic) |
| `egress_regression_test.py` | proves the Finding 2 fix preserves legitimate allowlisted traffic |
| `README.md` | per-patch detail and verification output |

Both patches are against station-v0.78 and were authored and tested against
copies — the live install was never modified and both files remain byte-identical
to their pre-audit state.

---

## Areas audited that came up clean

Recorded so the negative results are usable too:

- **Team / delegated approval (T3).** Genuinely well-hardened. Approval
  signatures bind `{action_hash, request_envelope_id, decision}`, so cross-action
  replay fails. Dedup spans approvals *and* denials, so one approver signing
  twice counts once. `quorum < 1` rejected at mint and again at verify. Self
  excluded from quorum. TTL expiry enforced. Deny wins. The CLI verifier mirrors
  the station-side logic rather than diverging.
- **MCP tool-call path.** No bypass found. The Phase A fix makes policy
  authoritative and the env var delivery-only; `require_human` + unset env
  refuses rather than auto-approving. One structural note below.
- **Receipt crypto primitives.** `receipt_signer.py` is clean — canonical JSON,
  sorted keys, Ed25519, no key material in errors.
- **Credential resolution error paths.** No plaintext credential reaches a log,
  exception, or receipt on the paths I read: HTTP helpers surface status plus
  response body only, never request headers; `_resolve_secret_ref` errors name
  the ref, never the value.

### One MCP observation, short of a finding

The whole policy gate sits inside `if _would_run_live(provider):`
(`mcp_server.py:774`), and that predicate infers "mock" from the *presence* of a
config key, never from where it points:

```python
    return not any(k.endswith("_API_BASE") or k in ("MOCK_BASE", "MOCK_BASE_URL")
                   for k in (ve if isinstance(ve, dict) else {}))
```

**Inferred, not tested:** a provider vault entry carrying e.g. `STRIPE_API_BASE`
pointed at a real endpoint is treated as not-live, skips the gate entirely, and
falls through to `engine.approve()` at line 837. Requires vault write access, so
it's not a remote path — but an operator pointing a connector at a staging base
would not expect human approval to switch itself off as a side effect.

### Marketplace replay surface

The metering path builds a one-time nonce with an explicit anti-replay comment
(`railcall_cli.py:543–551`). `_marketplace_authed_request`, which carries
`/org/vault-config` and publish, sends only `Content-Type` and `Authorization`
— no nonce, timestamp, idempotency key, or request signature; `/org/vault-config`
caches on a 5-minute TTL with no ETag. Replay requires the bearer token, and
anyone holding it can mint fresh requests anyway, so this is low severity. The
concrete gaps are no idempotency on publish and no freshness binding on config
fetches. Server-side rate limiting is not observable from the client and I did
not probe the production API to find out.
