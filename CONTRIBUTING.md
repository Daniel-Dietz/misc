# Contributing scripts

The goal is to **preserve useful work and make it discoverable**, whether it is a maintained utility, a one-time workaround or an incomplete historical reference. **A script does not need to meet production-readiness, portability or test-coverage standards just to be archived here.** We should be able to tell what it solved and how risky it would be to reuse.

## Minimum for every script (including one-offs)

- [ ] Add or update **one README quick-reference entry**, with relative link, concrete purpose/issue solved, status and runtime/context when known.
- [ ] Choose **Reusable**, **Adapt first** or **Reference only**. If there is a known material security problem or unsafe behavior, append **UNSAFE** and say precisely why. An untested script must not be described as validated.
- [ ] Explain the original task or incident, relevant environment/assumptions, what worked (if known) and what would have to change before reuse.
- [ ] Disclose **known risks**, data deletion/overwrites, required privileges, dependencies, external service calls and missing checks as far as they are known. Clearly label unknowns instead of inventing guarantees.
- [ ] Provide this context in a brief file header or nearby documentation linked from the README. If preserving an exact historical script is important, **a companion note is fine**; no refactoring is required just to keep it.
- [ ] Remove credentials, secrets, tokens, private keys and sensitive production data. Use obvious sanitized placeholders if needed.

These are **documentation and disclosure requirements**, not a demand to make every archived script safe to execute. Reference-only code may be insecure, incomplete, non-idempotent, untested or environment-specific **if that is visible and explained**. Never imply that an untested workaround is a production-ready solution.

## When creating or maintaining a reusable utility

Use [docs/SCRIPT-STANDARD.md](docs/SCRIPT-STANDARD.md) as the engineering target:

- Document **each function**, including helpers: purpose, parameters, return values or output, side effects, errors and external dependencies.
- Document CLI usage, versions, prerequisites, examples, inputs/outputs, security model and recovery.
- Prefer safe defaults, parameter validation, meaningful exit codes, least privilege, idempotency and dry-run support for risky actions.
- Run appropriate syntax/static checks and functional tests, including important failure scenarios, and state what was actually validated.
- For backup, restore and cleanup tools, describe retention, exclusion rules, consistency, verification, destructive scope and recovery.

If a previously archived script becomes maintained/reusable, improve its documentation and safeguards as part of that transition. Lack of these improvements **does not prevent its continued inclusion as a clearly labeled reference**.

## Review and maintenance

Review a **Reference only** submission primarily for usefulness, intelligible context, accurate warnings and secret removal—not cosmetic style or production-readiness. Review a **Reusable** submission more rigorously for code-level documentation, correctness, safety and testing.

When moving, renaming or removing scripts, update the README entry and any companion links. Do not index scripts that have not actually been committed. For the Bash starting point see [templates/script-template.sh](templates/script-template.sh).
