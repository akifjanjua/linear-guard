# Security

## Credential handling

Linear Guard does not contain a Linear API key in source code, module metadata, command inputs, logs, or receipts.

The API key is loaded from the local RailCall integration credential store. Users should configure it only through **RailCall Studio → Integrations**. Do not commit credential files or copy the local RailCall workspace into a release archive.

Never publish:

- `.env` files;
- `credentials.local.json`;
- `keys.local.json`;
- API keys;
- approval codes;
- local receipt archives;
- screenshots containing credentials or full sensitive identifiers.

## Transport security

The module keeps certificate and hostname verification enabled.

It first uses Python's verified HTTPS stack. On Windows certificate-chain verification failures, it may retry using the system `curl` executable with verification still enabled. The implementation does not use `CERT_NONE`, `check_hostname = False`, `curl -k`, or `--insecure`.

## Governance

The following operations are declared `write_requires_approval`:

- `linear.create_issue`;
- `linear.update_issue`;
- `linear.add_comment`.

A write must be bound to the exact approved payload. Without matching human approval, RailCall returns a blocked receipt and does not touch the Linear API.

## Failure behaviour

The module fails closed when:

- the credential is missing or malformed;
- required input is missing;
- an input type or allowed range is invalid;
- Linear returns GraphQL errors;
- Linear returns an unsuccessful mutation payload;
- the network request fails;
- rate limiting occurs;
- a write has no matching approval.

## Responsible disclosure

Do not place credentials, private issue contents, personal emails, approval codes, signatures, or full UUIDs in public issue reports. Provide a redacted reproduction and the RailCall/Linear versions involved.
