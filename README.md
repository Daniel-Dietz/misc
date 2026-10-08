# Miscellaneous Scripts & Utilities

A home for **small, standalone, reusable or potentially reusable scripts** that do not warrant a dedicated repository. Examples include backup/restore helpers, one-off maintenance procedures, administrative tools, diagnostics, migration helpers and single-file automations.

This repository is **not** a dumping ground for undocumented experiments, secrets, generated output or project-specific code that belongs in its own repository. Scripts should be understandable, auditable and safely reusable by someone other than the original author.

## Quick reference

**Every executable or utility added to the repository must have exactly one entry here.** Use a relative Markdown link to the actual file; write a concise purpose statement, not just the language. Keep entries sorted by file path. Documentation and templates are listed separately.

| File | Purpose | Runtime / platform |
| --- | --- | --- |
| _No utility scripts added yet._ | Add scripts here as they are introduced. | — |

### Documentation and templates

| File | Purpose |
| --- | --- |
| [CONTRIBUTING.md](CONTRIBUTING.md) | Short checklist for adding or changing scripts and updating this index. |
| [docs/SCRIPT-STANDARD.md](docs/SCRIPT-STANDARD.md) | Mandatory documentation, safety, security and quality conventions. |
| [templates/script-template.sh](templates/script-template.sh) | Documented Bash starting point; copy and adapt for a real utility. |

## Organization

- Keep simple, independent scripts under `scripts/<category>/<descriptive-name>.<ext>` (for example `scripts/backup/`, `scripts/maintenance/`, `scripts/network/`, `scripts/diagnostics/`, `scripts/migration/`). Create a category only when needed.
- Keep multi-file assets required by a script beside it or in a clearly named subdirectory; if it becomes a maintained application or substantial project, move it to its own repository.
- The script file is the main source of truth for usage and implementation details. Put optional extended operational guides under `docs/` and link them from the script header.
- Prefer standard libraries, explicit runtime requirements and minimal dependencies.
- Never commit credentials, production data, private keys, machine-specific personal configuration or unreviewed backups.

## How to use

1. Find the utility by file name or purpose in **Quick reference**.
2. Read its header for prerequisites, supported platforms, required permissions, arguments, side effects and examples.
3. Inspect the implementation and run `--help` when provided. Test with dry-run or a non-production target whenever supported.
4. Review backups, cleanup scope and recovery instructions before any destructive action.

**Important:** Scripts are provided as operational tools, not universally safe commands. Check the individual script’s assumptions and environment before running it.

## Adding or changing a utility

Follow [CONTRIBUTING.md](CONTRIBUTING.md) and [the script standard](docs/SCRIPT-STANDARD.md). In particular, **document every function and its parameters, return values and side effects**, including helpers. Code-level documentation is mandatory, not optional. Every new script must be indexed in this README in the same change.
