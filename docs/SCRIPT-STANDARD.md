# Script and code-level documentation standard

This repository is **both an operational toolbox and an archive of solutions**. The minimum below helps future readers understand a script and its risks. The fuller engineering practices are expected when **developing or maintaining a reusable utility**; they are **not admission criteria for one-off fixes, snapshots, experiments or imperfect historical code**.

**Core rule:** Prefer understandable, safely reusable scripts. If a script is not ready for reuse, **say why** and document **the particular problem it was created to solve**. Do not silently pass off historical or insecure code as production-ready.

## 1. Classify intended use and risks

Use the same labels in the README index and the script header or companion note:

- **Reusable:** intended for repeat use; apply the function documentation, robustness and validation expectations below.
- **Adapt first:** useful as a starting point for a different environment or recurrence of a similar incident; identify required adaptations and incomplete checks.
- **Reference only:** historical, incomplete, experimental, untested or otherwise retained for learning rather than direct execution.
- **UNSAFE:** an additional prominent flag when known vulnerabilities, insecure assumptions or materially unsafe behavior exist (e.g. **Reference only — UNSAFE**). Explain the specific risk, such as unsafe permissions, unbounded deletion, unvalidated input, disabled security checks or sensitive logging.

A script's **status is not proof of security**. Distinguish **known unsafe** from **not reviewed / unverified**; both deserve clear warnings, but lack of testing alone does not prove a vulnerability.

## 2. Minimum archival record — all scripts

Include a small comment header in the script **or** a linked adjacent Markdown note when preserving the exact original code is important. Capture what is known:

1. **Purpose and history:** the specific job, issue or incident solved; observed outcome if known.
2. **Context:** intended language, platform, service/version and any host-specific assumptions when known.
3. **Invocation:** how it was used, prerequisites and required privileges where known; do not invent a tested command.
4. **Effects:** files, data, services, network access or accounts it reads or changes; especially delete/overwrite/restart behavior.
5. **Status, verification and gaps:** use the labels above; state whether it was tested and what is incomplete or unknown.
6. **Risks before reuse:** known security flaws, destructive operations, missing safeguards, outdated dependencies and likely modifications required.

Keep the **README quick-reference row** aligned with that information. For an old snippet with incomplete historical context, say so directly (for example, "Original target version unknown; not retested"). A long manual, full parameterization, test suite or refactor is **not required to retain reference-only material**.

**Always remove live credentials, tokens, keys and sensitive production data before committing.** Mark where placeholders were substituted.

## 3. Function-level documentation — strong default for maintained scripts

Code-level documentation is a priority in this repository. For **Reusable** scripts, document **every declared function/method**, public and internal, close to its definition:

1. **Purpose and contract:** what it does and why.
2. **Arguments:** names, types/formats, constraints and defaults where applicable.
3. **Results:** return value, stdout/pipeline output, exit status or explicitly no meaningful output.
4. **Side effects:** files, network, services, process/global state and external calls.
5. **Failure cases:** material errors and caller-visible behavior.

Use language-appropriate forms: Bash documentation comments; PowerShell comment-based help (`.SYNOPSIS`, `.PARAMETER`, `.OUTPUTS`); Python docstrings (Args/Returns/Raises). Explain non-obvious external commands, API endpoints, configuration keys and protocol assumptions, including **why** unusual operations are necessary.

For **Adapt first** scripts, aim for the same standard where practical and mark documentation gaps. For **Reference only**, retaining imperfect original comments or undocumented helpers is acceptable **if the limitations are disclosed**. Do not rewrite a historical artifact solely to satisfy a documentation quota.

## 4. Engineering expectations for maintained/reusable utilities

When actively developing a reusable tool, provide a clear file header covering purpose, supported versions, dependencies, permissions, CLI usage with examples, inputs/outputs, safety, security, failure behavior and recovery.

- Default to least privilege and non-destructive operations. Prefer a real `--dry-run` for bulk and destructive changes.
- Validate prerequisites and inputs before changes; avoid unbounded deletion, dangerous paths, injection and surprising side effects.
- Favor rerun safety/idempotency when practical; document exceptions.
- Quote shell expansions correctly, use temporary files safely, handle interrupts and propagate failures with actionable diagnostics.
- Avoid leaking secrets into logs and arguments; use appropriate configuration methods.
- For backup/restore/cleanup scripts, document consistency requirements, the exact retention/deletion scope, verification and restore/recovery steps.

These are **improvement goals rather than archive-entry gates**. An old script that lacks them can remain here as **Adapt first** or **Reference only**, with **UNSAFE** added for any known material weakness. Merely writing a warning does **not** make the code safe to run.

## 5. Validation and lifecycle

For **Reusable** scripts, run an appropriate syntax/static check and targeted functionality/failure tests (for example `bash -n` / ShellCheck, PSScriptAnalyzer, Python compilation/tests). Record tested environments and important limitations; never report tests that were not performed.

For **Adapt first** and **Reference only** scripts, **testing is optional for archival**. State **not tested / unverified** when appropriate and preserve any known success or failure evidence without claiming broader compatibility.

When promoting old code to maintained use, improve the documentation, tests and safeguards. When behavior, intended use or risk changes, update the header or companion note and the README entry. Keep links accurate.

## 6. File organization and starting point

Choose descriptive paths under `scripts/<category>/`, including `incidents/` or `reference/` if useful. Language and category conventions are guidance, not prerequisites for keeping a historically useful filename.

The [Bash script template](../templates/script-template.sh) illustrates full inline documentation for a newly maintained utility. **Archived one-offs are not required to adopt the template.**
