# Troubleshooting Reference

## Linear credentials are not configured

Create a Linear personal API key and save it as `LINEAR_API_KEY` in **RailCall Studio → Integrations → Linear**. Linear Guard uses only RailCall's `vault_get("linear")` helper; local credential-file fallbacks are intentionally unsupported.

## `No module named certifi`

Install certifi with the same Python used by RailCall:

```bash
python -m pip install certifi
python -c "import certifi; print(certifi.where())"
```

## `CERTIFICATE_VERIFY_FAILED`

Confirm certifi is installed and current, then verify the computer date and time. Linear Guard never disables certificate or hostname verification and never falls back to curl.

## `blocked_by_policy`

This is expected for create, update, and comment operations without matching approval. Open **Studio → Sends**, inspect the exact payload, and approve it.

## Write outcome is unknown

Do not immediately retry. Open Linear and check whether the issue, update, or comment exists. Linear Guard performs no automatic mutation retry because a connection failure may occur after Linear has accepted the write.

## Approved action does not execute

Approval is bound to exact inputs. Changing punctuation, whitespace, title, body, identifier, or another field creates a different payload and requires a new approval.

## Module rejected after replacing files

Run `python tools/sign_module.py`, then copy `module.json`, `module.sig`, and `handlers/handler.py` together and reload Modules.

## Long JSON output

Continue from `next_offset` while `has_more` is true. Do not parse a visibly truncated receipt field.

## Rate limit reached

Wait before retrying. Narrow searches and reuse discovered IDs. Writes are never automatically retried.
