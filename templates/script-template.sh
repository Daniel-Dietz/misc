#!/usr/bin/env bash
#
# Name: script-template.sh
# Purpose: Reference template for a documented standalone Bash utility.
# Repository status: Template/example; not a deployed utility.
# Scope: Demonstration only; does not change data or implement a real task.
# Runtime: Bash 4.4+ on Linux (illustrative; not tested on every platform).
# Dependencies: Bash built-ins only.
# Permissions: No elevated privileges required.
# Usage: bash templates/script-template.sh [--help] [--dry-run]
# Inputs: Optional command-line switches.
# Outputs: Usage/help or a non-destructive status message on stdout.
# Side effects: None; no filesystem or network writes.
# Exit status: 0 for normal operation/help; 2 for invalid arguments.
# Security: No secrets or external configuration.
# Known limitations: This template is not a working operational script;
#   adapt the metadata, implementation and safety review for real use.
# Recovery: None needed; this template changes no data.
#
set -euo pipefail

# Print the supported CLI contract.
# Arguments: None.
# Output: Help text on stdout.
# Return status: 0.
# Side effects: None.
# Failures: The caller receives a non-zero status if stdout cannot be written.
usage() {
  cat <<'USAGE'
Usage: script-template.sh [--help] [--dry-run]

A non-destructive template. Copy and adapt; do not use it as a backup tool.
  --help       Show this help.
  --dry-run    Demonstrate the intended safe default.
USAGE
}

# Parse command-line options and run the demonstration safely.
# Arguments: All CLI tokens are passed positionally, as received.
# Output: A demonstration message on stdout or usage/errors on stdout/stderr.
# Return status: 0 for valid invocation; 2 for unknown arguments.
# Side effects: None. No writes, deletions or external service calls.
# Failures: Invalid options return 2; stdout failures propagate.
main() {
  local dry_run=true

  while (($#)); do
    case "$1" in
      --help) usage; return 0 ;;
      --dry-run) dry_run=true ;;
      *) printf 'Unknown argument: %s\n' "$1" >&2; usage >&2; return 2 ;;
    esac
    shift
  done

  if [[ "$dry_run" == true ]]; then
    printf '%s\n' 'Template only: no changes performed.'
  fi
}

main "$@"
