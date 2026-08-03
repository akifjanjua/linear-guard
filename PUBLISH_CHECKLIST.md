# Linear Guard v1.5.1 Publish Checklist

## 1. Work on a separate branch

```bash
cd ~/Projects/linear-guard
git switch feature/v1.5.1-v045-egress-contract
```

Do not alter the published v1.4.0 tag.

## 2. Install the transport dependency

Use the same Python RailCall uses:

```bash
python -m pip install certifi
python -c "import certifi; print(certifi.where())"
```

## 3. Run offline validation

```bash
python -m py_compile handlers/handler.py
python -m json.tool module.json > /dev/null
python tools/validate_release.py
python tools/security_test.py
python tools/v15_read_test.py
python tools/v15_triage_test.py
python tools/v15_plan_sprint_test.py
python tools/v15_rebalance_sprint_test.py
```

Every validation and test command must end in PASS.

## 4. Test with the real Linear API

Start RailCall Studio, install the module from the project path, reload Modules, and run:

```bash
python tools/smoke_test.py --issue RAI-9
```

Expected: all ten reads pass; all six writes are previewed only; no write executes.

Then separately test `linear.triage_issue`, `linear.plan_sprint`, and `linear.rebalance_sprint` against dedicated test issues, preserving the signed receipts and real Linear results.

## 5. Sign the exact release bytes

```bash
python tools/sign_module.py
```

Expected:

```text
Module signed successfully.
Signature verified locally.
Signature bytes: 64
```

Any later edit to `module.json` or `handlers/handler.py` requires signing again.

## 6. Build the archive

```bash
python tools/build_release.py
python tools/release_acceptance_test.py
```

Confirm the archive is `dist/linear-guard-v1.5.1.zip`, every packaged hash matches the generated release manifest, a simulated Windows CRLF checkout rebuilds it byte-for-byte, extracted `tools/validate_release.py` passes, and no credentials, receipts, approval codes, patches, caches, or local workspace files are present.

## 7. Fresh buyer rehearsal

From outside the source directory:

1. install the published marketplace version;
2. configure `LINEAR_API_KEY` through the Linear vault entry;
3. run `linear.get_current_user`;
4. search an issue;
5. preview an update;
6. approve one harmless update;
7. verify the signed receipt.

Target: under five minutes with no manual editing of installed files.

## 8. Listing metadata

Paste only the buyer-facing copy from `MARKETPLACE_LISTING.md`. Confirm:

- version `1.5.0`;
- `contest:2026Q3` remains present;
- no template headings are visible;
- homepage and tests URLs are valid;
- `video_url` is an unlisted YouTube walkthrough when ready.

## 9. Publish once

```bash
railcall market publish .
```

Do not repeatedly publish while debugging.

## 10. Reviewer reply

State that all three blockers were fixed: vault-only credentials, no curl/subprocess, and a complete auth manifest. Also mention the 16-command surface, homepage/tests URL, CI workflow, governed composites, receipt-safe evidence sharding, no mutation retries, and the demo video.
