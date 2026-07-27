# Evidence and Screenshot Checklist

The Freelancer entry accepts PNG, JPG, JPEG and GIF files. Use clean, readable screenshots and avoid exposing secrets.

## Recommended final evidence set

### 1. Module loaded

Show:

- Linear Guard `v1.3.0`;
- signature verified;
- one module loaded;
- zero rejected;
- all ten registered commands.

Suggested filename:

```text
01-linear-guard-module-loaded.png
```

### 2. Unapproved write blocked

Show the terminal output containing:

```text
execution_class: blocked
result_status: blocked_by_policy
approval_requirement: required
external_api_touched: False
```

Suggested filename:

```text
02-write-blocked-before-approval.png
```

### 3. Approval airlock executed

Show **RailCall Studio → Sends** with the Linear update or comment card displaying:

```text
EXECUTED
http = 200
sig = present
```

Suggested filename:

```text
03-airlock-approved-and-executed.png
```

### 4. Independently verified receipt

Show the executed `linear.update_issue` or `linear.add_comment` receipt and the successful independent verification result.

Suggested filename:

```text
04-signed-receipt-verified.png
```

### 5. Real Linear result

Show the `RAI-9` detail page with:

- updated issue title;
- priority set to High;
- activity entries for the update;
- the governed comment visible.

Suggested filename:

```text
05-real-linear-result.png
```

### 6. Marketplace listing

After publication, show the public Linear Guard listing, creator name, version and install control.

Suggested filename:

```text
06-marketplace-listing.png
```

## Redact before submission

Hide or crop:

- API keys;
- approval codes;
- email addresses unless intentionally public;
- full UUIDs;
- long hashes and raw signatures;
- local credential paths when unnecessary;
- browser tabs or notifications containing personal information.

Keep visible:

- command names;
- module version;
- status labels;
- HTTP 200;
- `external_api_touched`;
- issue identifier `RAI-9`;
- the human-approved comment;
- signature verification success.

## Suggested order in the contest gallery

1. real Linear result;
2. module loaded with ten commands;
3. blocked-before-approval evidence;
4. airlock execution;
5. independently verified receipt;
6. marketplace listing.

Lead with the business result, then prove the governance.
