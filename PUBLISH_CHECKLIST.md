# Linear Guard v1.5.6 Publish Checklist

## 1. Prepare and commit every signed source change

Work on a release branch. Run the complete static, security, Station v0.45, read, triage, sprint-planning, and sprint-rebalancing test suites.

Before signing, commit every change except `module.sig`:

```bash
git add -A
git restore --staged module.sig
git diff --cached --check
git commit -m "Prepare Linear Guard v1.5.6 signed-tree release"
```

The working tree must then be clean before signing. Confirm it with:

```bash
git status --porcelain --ignored
```

The signed tree is built by walking the working directory, not by reading Git. Any untracked file that is not covered by `.moduleignore` — a `*.backup-*` copy, an editor stray, a scratch note — is hashed into the tree manifest and signed, but is absent from a CI checkout, so the signature fails there while passing locally. `.moduleignore` excludes the predictable cases; `tools/sign_module_tree.py` refuses to sign anything else that differs from `HEAD`.

## 2. Sign with the repository signer, not the RailCall CLI

```bash
python tools/sign_module_tree.py .
python tools/verify_module_tree.py .
railcall market module verify .
```

**Do not sign with `railcall market module sign`.** It unconditionally rewrites `module.json` with `json.dump(..., indent=2)` in text mode before signing, which on Windows reintroduces CRLF line breaks and destroys the newline-free manifest established in v1.5.4.

That matters beyond this repository. A station writes `module.json` from a wire string in text mode at install time, so an LF manifest arrives as CRLF and a CRLF manifest arrives as CR CR LF. Only a manifest with zero physical newline bytes survives installation on every platform. A CRLF manifest still passes CI — `.gitattributes` marks `module.json -text`, so the bytes commit and check out unchanged — and then fails on the buyer's machine, which is the worst possible place to discover it.

`tools/sign_module_tree.py` produces the identical payload, `canonical(module.json) + \n + tree_manifest`, without touching `module.json`. It refuses to sign when the tree differs from `HEAD` or when the manifest contains newline bytes. `railcall market module verify` remains the authoritative check and must still pass.

Confirm the manifest survived signing:

```bash
python -c "b=open('module.json','rb').read(); print(len(b), b.count(b'\n'), b.count(b'\r'))"
```

The last two numbers must both be `0`. If they are not, restore the minified manifest and sign again.

Commit the generated signature:

```bash
git add module.sig
git commit -m "Sign Linear Guard v1.5.6 module tree"
```

Because `module.sig` is excluded from the signed v2 tree, committing the signature does not change the signed payload.

Editing any other tracked file — including this checklist and `CHANGELOG.md` — does change the signed payload and requires signing again.

## 3. Verify the committed tree

```bash
python tools/verify_module_tree.py .
railcall market module verify .
```

Both verifiers must report a valid v2 tree signature with 16 commands.

Verify a clean checkout too, since that is what CI and the marketplace see:

```bash
git clone --branch <release-branch> . /tmp/linear-guard-ci-check
python /tmp/linear-guard-ci-check/tools/verify_module_tree.py /tmp/linear-guard-ci-check
```

## 4. Build and accept the release

```bash
python tools/build_release.py
python tools/release_acceptance_test.py
```

The build reads exact blobs from Git `HEAD`; it does not normalize or rewrite signed files. The ZIP contains exactly RailCall's committed module tree plus `module.sig`, respecting `.moduleignore` and RailCall's built-in exclusions. The per-file release manifest is generated beside the ZIP, never inside it.

Expected assets:

```text
dist/linear-guard-v1.5.6.zip
dist/linear-guard-v1.5.6.files.json
```

## 5. Push, review, and merge

Push the signed branch and wait for Python 3.10, 3.12, and 3.13 CI. Merge only after every check passes.

After merging, update local `main` and repeat:

```bash
python tools/verify_module_tree.py .
railcall market module verify .
python tools/build_release.py
python tools/release_acceptance_test.py
```

Do not tag or publish if any verifier fails.

## 6. Publish once

Publish the existing marketplace ID only from the verified clean `main` directory:

```bash
railcall market publish . --type=module
```

Do not repeatedly publish while debugging. Preserve the marketplace output and the final signed receipt evidence.

After publishing, install the published module on a Windows machine and run `railcall market module verify` against the installed directory. That is the only check that exercises the text-mode install path the newline-free manifest exists to survive.
