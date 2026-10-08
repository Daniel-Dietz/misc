# Script and code-level documentation standard

**Status: mandatory for all scripts in this repository.** Apply these conventions proportionately: a ten-line helper need not have a multi-page manual, but its behavior must still be explicit.

## 1. Scope and naming

Each script should do one operational job and be usable independently or with minimal companion files. Choose descriptive lowercase hyphenated names and the appropriate extension (for example `cleanup-immich-backups.sh`, `inspect-dhcp.ps1`, `check-config.py`). Do not rename an existing script solely for style. Prefer directory categories only when needed.

The README quick-reference index is the repository's discovery catalog. Include the **actual relative file path**, a one-sentence description and supported runtime/platform. Keep links accurate as files change.

## 2. Mandatory file header

At the top of **every script**, state:

- **Name and purpose:** what problem the script solves and what it explicitly does not do, if material.
- **Compatibility:** language/interpreter and tested operating systems or versions.
- **Prerequisites:** required commands, libraries, services, API privileges, files and network access.
- **Usage:** command syntax, flags/arguments and at least one safe example.
- **Inputs and outputs:** input sources and formats; output paths, formats and logs.
- **Effects and safety:** whether it is read-only, creates/overwrites/deletes data, restarts services or changes remote systems. Document confirmation, dry-run support or safeguards.
- **Failure and recovery:** exit code behavior, important error conditions, verification and how to recover from partial execution.
- **Security:** privileges required, handling of secrets and sensitive data; environment-specific assumptions.
- **Ownership/maintenance:** optional contact or source link, particularly for scripts derived from external projects.

Adapt comment syntax to the language (Bash `#`, PowerShell comment-based help, Python module docstrings, etc.). Never embed secrets in the header.

## 3. Mandatory documentation for each function

**Every declared function/method, public or internal, must have documentation at its definition.** Explain:

1. **Purpose and contract** — what the function does and when it is called.
2. **Arguments** — name, type or expected format, meaning, allowed range/defaults when applicable.
3. **Results** — returned value, stdout/output, status/exit behavior; say explicitly if there is no meaningful return.
4. **Side effects** — filesystem, network, services, process state, global variables or external commands it changes/calls.
5. **Failures** — important raised errors, non-zero results, and how callers handle them.

Use idiomatic documentation formats: PowerShell `.SYNOPSIS`, `.PARAMETER`, `.OUTPUTS`; Python PEP 257 docstrings with Args/Returns/Raises; Bash documentation blocks immediately before the function. Avoid made-up return contracts: in Bash, distinguish stdout data from function exit status; in PowerShell distinguish pipeline output from a process exit code.

Also document non-obvious *external references*: API endpoints, commands with surprising flags, environment variables, configuration keys and relevant third-party protocols. Link to upstream specifications when useful. Explain **why** an unusual step is needed, not merely what the code line does.

## 4. Robustness and operational safety

- Default to least privilege and non-destructive behavior. Prefer `--dry-run` for cleanup, replacement and bulk changes; when unavailable, document why and provide precise safeguards.
- Validate prerequisites and input values **before** applying changes. Avoid broad glob/deletion targets; canonicalize and check target paths, reject dangerous/empty values, and state the exact retention policy.
- Make re-runs idempotent where practical. Explicitly flag operations that are not safe to retry.
- Implement clear success/failure reporting and meaningful non-zero failures. Preserve original errors; do not hide failures behind permissive handlers.
- Quote shell expansions and defend against whitespace, special characters, unexpected filenames and injection.
- Treat credentials as sensitive: do not hardcode or echo them; avoid secrets in command-line arguments if safer alternatives exist. Do not commit `.env` or real backup data.
- Use temporary files safely and clean them up without deleting user data. Handle interrupts where applicable.
- For backups, explicitly describe consistency requirements, verification, retention, restore steps and the separation between backing up and deleting old archives.

## 5. Validation and maintenance

Each change must specify an appropriate check, such as `bash -n`, `shellcheck`, PowerShell parsing/PSScriptAnalyzer, Python compilation/linting or focused unit tests. Test the documented happy path plus significant failure paths, preferably in a disposable environment. If production systems or credentials are needed and tests could not be run, state that clearly rather than claiming success.

For any change affecting usage, requirements, safety or behavior, update the header and function documentation at the same time. Update the README index for additions, deletions, moves or changed purposes. Do not leave stale examples or dead links.

## 6. Script template

Start from [the Bash template](../templates/script-template.sh) for Bash-based utilities, adapting rather than copying unneeded options. Other languages must follow the **same documentation contract** using native syntax.
