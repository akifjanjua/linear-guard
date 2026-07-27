# Publish Checklist

## A. Add the submission files to the real project

Copy these files and folders into:

```text
C:\Users\Muhammad Akif Janjua\Projects\linear-guard
```

Do not overwrite your working `module.sig` until the module is re-signed locally.

## B. Validate the release

From Git Bash:

```bash
cd ~/Projects/linear-guard

python -m py_compile handlers/handler.py
python -m json.tool module.json > /dev/null
python tools/validate_release.py
```

Run the safe runtime test while Studio is running:

```bash
python tools/smoke_test.py --issue RAI-9
```

The smoke test performs reads and write previews only. It does not approve or execute writes.

## C. Re-sign after adding or changing signed files

```bash
python tools/sign_module.py
```

Confirm:

```text
Module signed successfully.
Signature verified locally.
Signature bytes: 64
```

## D. Build a clean local release archive

```bash
python tools/build_release.py
```

The archive is written under `dist/` and excludes credentials, local receipts and temporary test output.

## E. Final local module check

Copy the newly signed files into the installed module directory, reload all modules and confirm:

- version `1.3.0`;
- signature verified;
- one loaded;
- zero rejected;
- ten registered commands.

## F. Marketplace account

Confirm the marketplace dashboard shows:

- active seller profile;
- publisher key registered;
- public creator profile completed;
- email verified if required.

## G. Publish

From the project root:

```bash
railcall market publish .
```

Follow the review/publishing prompts. Do not publish from the `.railcall` folder or from a folder containing credentials.

## H. Listing description

Use the copy in `MARKETPLACE_LISTING.md` and ensure this exact tag appears:

```text
contest:2026Q3
```

## I. Pre-publish review

Reviewers should be able to verify:

- real Linear API calls;
- ten useful actions;
- local secret handling;
- honest failures;
- blocked writes before approval;
- signed receipts;
- installation and setup in under ten minutes.

## J. Contest entry

After the listing is public:

1. copy the public marketplace listing URL;
2. paste it into `CONTEST_SUBMISSION.md`;
3. upload the selected evidence images to Freelancer;
4. use the prepared title and description;
5. submit before the contest deadline.

## K. First 72 hours

Share the public listing with relevant developers and ask them to install and test it honestly. Do not spam. Respond quickly to installation problems and record any fixes in the changelog.
