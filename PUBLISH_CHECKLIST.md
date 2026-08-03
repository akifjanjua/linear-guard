# Linear Guard v1.5.2 Publish Checklist

## 1. Prepare and commit every signed source change

Work on a release branch. Run the complete static, security, Station v0.45, read, triage, sprint-planning, and sprint-rebalancing test suites.

Before signing, commit every change except `module.sig`:

```bash
git add -A
git restore --staged module.sig
git diff --cached --check
git commit -m "Prepare Linear Guard v1.5.2 signed-tree release"
```

The working tree must then be clean before the official signing command.

## 2. Sign only with RailCall

```bash
railcall market module sign .
railcall market module verify .
```

The signer may change only `module.sig`. If `module.json` also changes, commit that manifest change, sign again, and verify again.

Commit the generated signature:

```bash
git add module.sig
git commit -m "Sign Linear Guard v1.5.2 module tree"
```

Because RailCall excludes `module.sig` from the signed v2 tree, committing the signature does not change the signed payload.

## 3. Verify the committed tree

```bash
python tools/verify_module_tree.py .
railcall market module verify .
```

Both verifiers must report a valid v2 tree signature with 16 commands.

## 4. Build and accept the release

```bash
python tools/build_release.py
python tools/release_acceptance_test.py
```

The build reads exact blobs from Git `HEAD`; it does not normalize or rewrite signed files. The ZIP contains exactly RailCall's committed module tree plus `module.sig`, respecting `.moduleignore` and RailCall's built-in exclusions. The per-file release manifest is generated beside the ZIP, never inside it.

Expected assets:

```text
dist/linear-guard-v1.5.2.zip
dist/linear-guard-v1.5.2.files.json
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
