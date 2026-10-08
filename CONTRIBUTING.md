# Contributing scripts

The goal is **small, reusable, reviewable and well-documented tools**.

## Checklist for every new or modified script

- [ ] Scope fits this repository; one clear responsibility and a descriptive file name/path.
- [ ] Update the **README quick-reference table** with a working relative link, purpose and runtime/platform; remove or update old entries when renaming/deleting.
- [ ] Add or update a header describing purpose, requirements, permissions, invocation, inputs, outputs, side effects, safety and examples.
- [ ] Document **every function** (including private/helper functions): purpose, parameters and accepted values, return/output/exit behavior, side effects, relevant errors and external calls where applicable.
- [ ] Add comments explaining non-obvious decisions, assumptions, protocol interactions and risky operations. Do not substitute obvious line-by-line comments for meaningful explanations.
- [ ] Use safe defaults, validate inputs, quote/escape values correctly, and avoid hidden destructive behavior. Explicitly describe deletion, overwrite, network changes and privilege requirements.
- [ ] Keep secrets, credentials, host-specific sensitive values and real datasets out of commits and examples.
- [ ] Provide at least a syntax/static check and a targeted test or documented manual verification step; include expected results and limitations.
- [ ] Make dependencies explicit; pin versions only where technically needed; document supported versions.
- [ ] Ensure diagnostics are actionable and exit codes are meaningful. Never silently ignore failures.
- [ ] For backup/restore and cleanup scripts, document what is retained, what is deleted, exclusion rules, verification of success and recovery procedure.

See [docs/SCRIPT-STANDARD.md](docs/SCRIPT-STANDARD.md) for the full rules and [templates/script-template.sh](templates/script-template.sh) for an example.

## Review expectation

Changes should be reviewable without running them on a production system. Review focuses on correctness, safety, reproducibility, understandable code and complete documentation, not cosmetic nitpicking. If a requirement does not apply, explain why in the script header or change description.

Do not add placeholder entries for scripts not yet committed.
