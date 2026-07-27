# Troubleshooting Reference

## `unauthorized`

Confirm the Linear API key is valid, saved under the Linear integration, and set as the default credential. Regenerate the key if it was exposed or revoked.

## `CERTIFICATE_VERIFY_FAILED`

Check the computer date/time and confirm `curl --version` works. Linear Guard does not disable TLS verification; it uses verified system curl as a fallback.

## `blocked_by_policy`

This is expected for create, update and comment operations without a matching approval. Open **Studio → Sends**, inspect the exact payload and approve it.

## Approved action does not execute

The approval is bound to exact inputs. Reuse the same saved JSON payload. Changing punctuation, whitespace, title, body or identifier creates a new approval requirement.

## Module rejected after replacing files

Re-run `python tools/sign_module.py`, copy `module.json`, `module.sig` and `handlers/handler.py` together, then reload all modules.

## Long JSON field cannot be decoded

Use the command's pagination fields. Continue from `next_offset` while `has_more` is true. Do not parse a visibly truncated receipt string.

## Comment not visible in the issue list

Comments appear inside the issue's detail/activity page, not in Linear's issue list. Open the issue and scroll to Activity.

## `rate limit reached`

Wait before retrying. Do not loop aggressively. Narrow searches and reuse discovered IDs.
