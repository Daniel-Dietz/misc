# Miscellaneous Scripts & Utilities

A long-term collection of **small scripts, workarounds and useful code examples** that do not fit naturally into another repository. The point is to preserve past work so a similar task can start from something useful rather than from zero.

This includes reusable operational tools, backup and maintenance helpers, diagnostics, migrations, **one-off incident fixes**, environment-specific commands, prototypes and historical examples. **A script does not have to be polished, portable, fully tested or production-ready to belong here.** A single-use script that solved one problem can be worth keeping.

> **Principle:** Scripts should be understandable and safely reusable **where practical**. Otherwise, clearly mark them as **unverified, unsafe or reference-only**, describe **the specific problem or one-off issue they solved**, and explain any known risks or changes needed before using them again. Saving an imperfect solution is useful; presenting it as generally safe is not.

## Quick reference

Use this table to find code by file name or by the problem it solved. **Add one row for every script**, including one-offs and reference-only examples, with a working relative link and a useful description. Keep entries sorted by path.

| File | What it does / problem solved | Status | Runtime / context |
| --- | --- | --- | --- |
| [scripts/accounting/Receive-KivitendoDatev.ps1](scripts/accounting/Receive-KivitendoDatev.ps1) | Pulls approved DATEV packets over pinned read-only SSH, verifies client/hashes and maintains local duplicate and interrupted-publication state; optional atomic handoff to Belegtransfer. | Adapt first | Windows 11, PowerShell 5.1, OpenSSH; [setup and limits](scripts/accounting/kivitendo-datev-handover.md) |
| [scripts/accounting/Test-KivitendoDatevReceiver.ps1](scripts/accounting/Test-KivitendoDatevReceiver.ps1) | Tests repeat runs, consumed-file deduplication, interrupted publication, wrong clients and corruption in private unwatched test directories. | Adapt first | Windows PowerShell 5.1; working reader and a received packet; retains private test files |
| [scripts/accounting/kivitendo-datev-extract.pl](scripts/accounting/kivitendo-datev-extract.pl) | Extracts monthly booking files and archived PDF references through the kivitendo console in a read-only transaction. | Adapt first | Perl; customized kivitendo 4.0.1 EXTF 700/13 exporter; [setup and limits](scripts/accounting/kivitendo-datev-handover.md) |
| [scripts/accounting/kivitendo-datev-handover.py](scripts/accounting/kivitendo-datev-handover.py) | Prepares immutable DATEV snapshots and an explicitly queued outbox with PDF/XML links, integrity checks and duplicate-period protection; no upload/import. | Adapt first | Python 3.11+, Linux, Perl XML::LibXML; [setup and limits](scripts/accounting/kivitendo-datev-handover.md) |
| [scripts/accounting/kivitendo-datev-serve.py](scripts/accounting/kivitendo-datev-serve.py) | Serves only approved outbox files through a restricted SSH command; rejects shell/path requests, changed packets, wrong clients and stale preparation. | Adapt first | Python 3.11+, Linux/OpenSSH; dedicated account and read-only ACLs required |
| [scripts/accounting/test-kivitendo-datev-handover.py](scripts/accounting/test-kivitendo-datev-handover.py) | Verifies archive metadata, PDF hashes and handover failure cases on temporary copies of a prepared snapshot. | Adapt first | Python 3.11+; requires a prepared snapshot |
| [scripts/accounting/test-kivitendo-datev-serve.py](scripts/accounting/test-kivitendo-datev-serve.py) | Checks the SSH reader with synthetic data, including arbitrary commands, traversal, symlinks, changed files, wrong clients and stale/failed sources. | Adapt first | Python 3.11+ standard library; no network or real accounting data |
| [scripts/maintenance/immich-post-update-cleanup.sh](scripts/maintenance/immich-post-update-cleanup.sh) | Retains the newest verified Immich upgrade backup, removes older upgrade/.env backups and obsolete Immich-stack images, and can explicitly prune unused dangling images after an update. | Reusable | Bash 4.4+, Linux, Docker Compose v2; developed from Debian 13 / Immich v3.3.0 maintenance |

### Status labels

- **Reusable** — intended for repeated use; still inspect its assumptions and risks before running.
- **Adapt first** — built for a particular host, environment or incident; use as a starting point and adjust it.
- **Reference only** — retained for ideas or historical context; incomplete, untested, outdated or otherwise not intended for direct execution.
- Add **UNSAFE** visibly to the status (for example, **Reference only — UNSAFE**) whenever a known security weakness or material unsafe behavior is present. Explain the *specific* issue in the file header or companion note. Labeling an issue does not fix it.

The status is an **intended-use description, not a security certification**. If the behavior has not been verified, say **not tested / unverified**; never imply it was tested.

### Documentation and templates

| File | Purpose |
| --- | --- |
| [CONTRIBUTING.md](CONTRIBUTING.md) | Minimal requirements for archiving scripts and higher standards for reusable utilities. |
| [docs/SCRIPT-STANDARD.md](docs/SCRIPT-STANDARD.md) | Documentation and safety conventions, with explicit allowances for one-offs and incomplete examples. |
| [templates/script-template.sh](templates/script-template.sh) | Documented Bash starting point for a new utility; optional for archived scripts. |

## Minimum context for anything stored here

Even an unfinished or unsafe one-off needs enough information for a future reader to understand why it is here:

1. **What happened / what it solves:** a concrete purpose, incident or use case, including relevant environment or version details *when known*.
2. **Intended use:** a status from above, how it was run (if known), and whether it actually worked or was tested.
3. **Risks and limits:** known unsafe or insecure practices, destructive side effects, special prerequisites, environment-specific assumptions and missing verification. State unknowns honestly.
4. **Discoverability:** an entry in the quick-reference table. Put the context in the script header or a linked companion note when keeping the original script unchanged.

**Do not commit real credentials, private keys, sensitive production data or backups.** Redact them even when preserving historical scripts.

Complete function documentation, input validation, safe defaults and tests are the **target for maintained/reusable utilities**, not a prerequisite for preserving every one-off. If documentation or safeguards are missing, **call out those gaps** rather than discarding useful reference material. See [the script standard](docs/SCRIPT-STANDARD.md).

## Organization

- Prefer `scripts/<category>/<descriptive-name>.<ext>` (for example `backup/`, `maintenance/`, `diagnostics/`, `migration/`, `incidents/` or `reference/` under `scripts/`). Create folders as needed; the categories are suggestions, not admission rules.
- Keep related notes or sample configuration (sanitized) beside the script when that makes the original problem easier to understand.
- A dedicated project belongs in its own repository when appropriate, but small partial implementations and one-off excerpts may still be preserved here for reference.
- Prefer few dependencies for maintained scripts. Historical scripts may retain obsolete dependencies if they are documented.

## Before using a script

1. Find it in the quick reference and check **status** and **known risks**.
2. Read the script and any associated notes. Confirm prerequisites, target system, permissions, file paths and side effects.
3. **Do not execute Reference only or UNSAFE code as-is.** Adapt and independently review it before use.
4. For cleanup, restore or other destructive operations, verify exact targets, backups and recovery steps. Prefer a test environment or dry run where available.

This repository is a **knowledge base as well as a toolbox**. Inclusion means that the code may be useful, **not that it is approved for production**.

## Adding or changing a script

Follow [CONTRIBUTING.md](CONTRIBUTING.md) and [docs/SCRIPT-STANDARD.md](docs/SCRIPT-STANDARD.md). Preserve the context and risks of one-offs; use the full documentation standard, including documenting each function and its side effects, when turning a script into a maintained reusable utility. Update this index with the script in the same change.
