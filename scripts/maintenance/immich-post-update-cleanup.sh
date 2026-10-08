#!/usr/bin/env bash
#
# Name: immich-post-update-cleanup.sh
# Status: Reusable — intended for repeated post-update maintenance after an
#         operator reviews the default dry-run on the target host.
# Context: Developed from an Immich v3.2.4 -> v3.3.0 maintenance cycle on a
#          Debian 13 Proxmox VM using Docker Compose, PostgreSQL 16/VectorChord,
#          Valkey and OpenVINO machine learning.
# Purpose: Safely clean obsolete Immich upgrade backups and Docker images after a
#          successful Docker Compose based Immich update.
# Scope: Retains exactly the newest matching upgrade-backup directory, removes
#        older matching upgrade backups and temporary .env backup files, and
#        removes obsolete images from the known Immich/Valkey stack repositories.
#        Containers, networks, Docker volumes and build cache are never removed.
# Runtime: Bash 4.4+ on Linux; intended for Debian/Ubuntu style Docker hosts.
# Prerequisites: Docker Engine, Docker Compose v2, GNU find/sort/cut/rm/df/realpath,
#                a valid Immich Compose project, and a running Compose service
#                named "database" whose image provides pg_restore.
# Permissions: Root is required for the default /root backup location and Docker.
# Usage:
#   immich-post-update-cleanup.sh
#   immich-post-update-cleanup.sh --apply
#   immich-post-update-cleanup.sh --apply --prune-dangling
#   immich-post-update-cleanup.sh --project-dir /opt/immich --backup-root /root
# Inputs: CLI options, the Compose project/.env, Docker metadata and local
#         immich-upgrade-* backup directories.
# Outputs: Human-readable cleanup plan/actions plus final Compose, image, Docker
#          disk-usage and root-filesystem reports.
# Side effects: Dry-run is the default. --apply deletes older matching upgrade
#               backups, loose .env backup files and unreferenced images from the
#               recognized Immich/Valkey repositories. --prune-dangling also
#               deletes all unused dangling Docker images on the host.
# Retention: The newest immich-upgrade-* directory by filesystem modification time
#            is kept. All older matching directories are deleted with --apply.
#            All matching loose .env.pre-*, .env.backup* and .env.bak* files are
#            deleted with --apply.
# Safety: Destructive mode requires the current Compose stack to be running and
#         healthy and the newest PostgreSQL dump to pass pg_restore --list.
#         Images referenced by any existing container or by the current Compose
#         configuration are protected. Docker volumes are never pruned.
# Failure/recovery: Strict Bash error handling stops on failed commands. Deletion
#                   is not transactional; after a partial failure, re-run without
#                   --apply, inspect the retained newest backup and current stack,
#                   then resume if appropriate. Use the retained database/config
#                   backup or hypervisor/storage snapshot for rollback.
# Security: The script never prints the full Compose environment or database
#           password. The retained .env backup can contain secrets and must remain
#           access-controlled. No credentials or host-specific secrets are stored
#           in this script.
# Verification: `bash -n` passed; `--help` passed; an invalid option returned
#               status 2; and a mocked end-to-end dry-run correctly retained the
#               newest backup while selecting stale backup/image artifacts.
#               ShellCheck was unavailable in the execution environment. This
#               repository copy has not been run with --apply on production.
# Validation before reuse: Run the default dry-run on the target host and inspect
#                          every KEEP/WOULD DELETE line before --apply. Use
#                          --prune-dangling only after reviewing host-wide images.
# Source: https://github.com/Daniel-Dietz/misc
#
set -Eeuo pipefail

PROJECT_DIR="/opt/immich"
BACKUP_ROOT="/root"
BACKUP_PATTERN="immich-upgrade-*"
APPLY=false
PRUNE_DANGLING=false

declare -A PROTECTED_IMAGE_IDS=()

# Print the supported command-line interface.
# Arguments: None.
# Output: Help text on stdout.
# Return status: 0 unless stdout cannot be written.
# Side effects: None.
# Failures: Shell I/O failures propagate.
usage() {
    cat <<'USAGE'
Usage: immich-post-update-cleanup.sh [options]

Safely clean obsolete Immich post-update artifacts. Dry-run is the default.

Options:
  --apply                 Perform the listed deletions.
  --prune-dangling        Also delete all unused dangling Docker images. This can
                          affect images unrelated to Immich.
  --project-dir PATH      Compose project directory (default: /opt/immich).
  --backup-root PATH      Parent of immich-upgrade-* backups (default: /root).
  --help, -h              Show this help.

Examples:
  immich-post-update-cleanup.sh
  immich-post-update-cleanup.sh --apply
  immich-post-update-cleanup.sh --apply --prune-dangling
USAGE
}

# Terminate execution with an actionable error.
# Arguments: $@ - Error text fragments.
# Output: One ERROR line on stderr.
# Return status: Does not return; exits 1.
# Side effects: Terminates the script.
# Failures: None beyond the explicit exit; stderr errors may also surface.
die() {
    printf 'ERROR: %s\n' "$*" >&2
    exit 1
}

# Parse CLI options and update global runtime configuration.
# Arguments: $@ - Raw CLI tokens.
# Output: Help text for --help; errors/usage for invalid options.
# Return status: 0 for valid input/help; exits 2 for invalid or incomplete options.
# Side effects: Updates PROJECT_DIR, BACKUP_ROOT, APPLY and PRUNE_DANGLING.
# Failures: Unknown options and missing option values exit 2.
parse_args() {
    while (($#)); do
        case "$1" in
            --apply) APPLY=true ;;
            --prune-dangling) PRUNE_DANGLING=true ;;
            --project-dir)
                (($# >= 2)) || { printf 'ERROR: --project-dir requires a path.\n' >&2; exit 2; }
                PROJECT_DIR="$2"
                shift
                ;;
            --backup-root)
                (($# >= 2)) || { printf 'ERROR: --backup-root requires a path.\n' >&2; exit 2; }
                BACKUP_ROOT="$2"
                shift
                ;;
            --help|-h)
                usage
                exit 0
                ;;
            *)
                printf 'ERROR: Unknown argument: %s\n' "$1" >&2
                usage >&2
                exit 2
                ;;
        esac
        shift
    done
}

# Validate prerequisites, canonicalize configured paths and validate Compose syntax.
# Arguments: None; consumes PROJECT_DIR and BACKUP_ROOT globals.
# Output: Docker/Compose diagnostics only if their commands fail.
# Return status: 0 on success; fatal validation errors exit 1 through die.
# Side effects: Canonicalizes PROJECT_DIR/BACKUP_ROOT and cd's to PROJECT_DIR.
# External calls: id/EUID, realpath, docker and `docker compose config --quiet`.
# Failures: Missing privilege/commands/files, unavailable Docker/Compose or invalid
#           Compose configuration stop execution before any deletion.
validate_environment() {
    local command_name

    [[ $EUID -eq 0 ]] || die "Run this script as root."

    for command_name in docker find sort cut grep rm df realpath; do
        command -v "$command_name" >/dev/null 2>&1 \
            || die "Required command not found: $command_name"
    done

    PROJECT_DIR="$(realpath -e -- "$PROJECT_DIR")" \
        || die "Project directory does not exist: $PROJECT_DIR"
    BACKUP_ROOT="$(realpath -e -- "$BACKUP_ROOT")" \
        || die "Backup root does not exist: $BACKUP_ROOT"

    [[ -f "$PROJECT_DIR/docker-compose.yml" ]] \
        || die "Missing $PROJECT_DIR/docker-compose.yml"
    [[ -f "$PROJECT_DIR/.env" ]] || die "Missing $PROJECT_DIR/.env"

    docker info >/dev/null 2>&1 || die "Docker daemon is not available."
    docker compose version >/dev/null 2>&1 || die "Docker Compose v2 is unavailable."

    cd "$PROJECT_DIR"
    docker compose config --quiet || die "Current Docker Compose configuration is invalid."
}

# Check that the current Compose deployment is suitable for post-update cleanup.
# Arguments: None.
# Output: Warnings for missing/stopped/unhealthy containers.
# Return status: 0 when safe, or during dry-run after warnings; --apply exits 1 if
#                the stack is incomplete, stopped or unhealthy.
# Side effects: None; Docker state is read only.
# External calls: docker compose config/ps and docker inspect.
# Failures: Unsafe runtime state blocks destructive mode.
validate_runtime_state() {
    local expected_count actual_count container_id status health unsafe=false
    local -a container_ids=()

    expected_count="$(docker compose config --services | grep -c . || true)"
    mapfile -t container_ids < <(docker compose ps -aq)
    actual_count="${#container_ids[@]}"

    if [[ "$expected_count" -eq 0 || "$actual_count" -ne "$expected_count" ]]; then
        printf 'WARNING: Compose container count is %s; expected %s.\n' \
            "$actual_count" "$expected_count" >&2
        unsafe=true
    fi

    for container_id in "${container_ids[@]}"; do
        status="$(docker inspect --format '{{.State.Status}}' "$container_id")"
        health="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{end}}' "$container_id")"
        if [[ "$status" != "running" ]]; then
            printf 'WARNING: Container %s state is %s.\n' "$container_id" "$status" >&2
            unsafe=true
        fi
        if [[ -n "$health" && "$health" != "healthy" ]]; then
            printf 'WARNING: Container %s health is %s.\n' "$container_id" "$health" >&2
            unsafe=true
        fi
    done

    if [[ "$unsafe" == true && "$APPLY" == true ]]; then
        die "Current Compose stack is not fully running/healthy; refusing cleanup."
    fi
}

# Retain the newest verified upgrade backup and remove older matching backups.
# Arguments: None; uses BACKUP_ROOT/BACKUP_PATTERN/APPLY globals.
# Output: KEEP/WOULD DELETE/DELETE lines and PostgreSQL dump verification status.
# Return status: 0 on success; destructive mode exits 1 if the newest backup is
#                missing required files or fails pg_restore validation.
# Side effects: With --apply, recursively deletes older backup directories only.
# External calls: GNU find/sort/cut/rm and `docker compose exec ... pg_restore`.
# Failures: An unverifiable newest backup blocks deletion of every older backup.
cleanup_upgrade_backups() {
    local newest_backup backup index backup_valid=true
    local -a backups=()

    mapfile -t backups < <(
        find "$BACKUP_ROOT" -mindepth 1 -maxdepth 1 -type d \
            -name "$BACKUP_PATTERN" -printf '%T@ %p\n' \
        | sort -nr | cut -d' ' -f2-
    )

    printf '%s\n' '=== UPGRADE BACKUPS ==='
    if ((${#backups[@]} == 0)); then
        printf 'WARNING: No %s/%s directories found; backup cleanup skipped.\n' \
            "$BACKUP_ROOT" "$BACKUP_PATTERN" >&2
        return 0
    fi

    newest_backup="${backups[0]}"
    printf 'KEEP: %s\n' "$newest_backup"

    [[ -f "$newest_backup/.env" ]] \
        || { printf 'WARNING: Newest backup has no .env.\n' >&2; backup_valid=false; }
    [[ -s "$newest_backup/docker-compose.yml" ]] \
        || { printf 'WARNING: Newest backup has no non-empty docker-compose.yml.\n' >&2; backup_valid=false; }
    [[ -s "$newest_backup/immich-postgresql.dump" ]] \
        || { printf 'WARNING: Newest backup has no non-empty PostgreSQL dump.\n' >&2; backup_valid=false; }

    if [[ "$backup_valid" == true ]]; then
        if docker compose ps --status running --services | grep -qx 'database' \
           && docker compose exec -T database pg_restore --list \
              < "$newest_backup/immich-postgresql.dump" >/dev/null 2>&1; then
            printf '%s\n' 'Newest PostgreSQL dump: VERIFIED'
        else
            printf '%s\n' 'WARNING: Newest PostgreSQL dump could not be verified.' >&2
            backup_valid=false
        fi
    fi

    if [[ "$backup_valid" != true ]]; then
        [[ "$APPLY" == true ]] \
            && die "Newest upgrade backup is not verified; refusing older-backup deletion."
        printf '%s\n' 'WARNING: Older-backup deletion skipped in dry-run.' >&2
        return 0
    fi

    for ((index=1; index<${#backups[@]}; index++)); do
        backup="${backups[$index]}"
        if [[ "$APPLY" == true ]]; then
            printf 'DELETE: %s\n' "$backup"
            rm -rf --one-file-system -- "$backup"
        else
            printf 'WOULD DELETE: %s\n' "$backup"
        fi
    done

    ((${#backups[@]} > 1)) || printf '%s\n' 'No older upgrade backups found.'
}

# Remove loose temporary .env backup files directly under the Compose project.
# Arguments: None; uses PROJECT_DIR and APPLY globals.
# Output: WOULD DELETE/DELETE lines or "None.".
# Return status: 0 on success; find/rm errors propagate.
# Side effects: With --apply, deletes only .env.pre-*, .env.backup* and .env.bak*;
#               the active .env does not match these patterns.
# Failures: Filesystem errors stop execution under strict Bash handling.
cleanup_env_backups() {
    local file found=false

    printf '%s\n' '=== LOOSE ENV BACKUPS ==='
    while IFS= read -r -d '' file; do
        found=true
        if [[ "$APPLY" == true ]]; then
            printf 'DELETE: %s\n' "$file"
            rm -f -- "$file"
        else
            printf 'WOULD DELETE: %s\n' "$file"
        fi
    done < <(
        find "$PROJECT_DIR" -mindepth 1 -maxdepth 1 -type f \
            \( -name '.env.pre-*' -o -name '.env.backup*' -o -name '.env.bak*' \) \
            -print0
    )

    [[ "$found" == true ]] || printf '%s\n' 'None.'
}

# Build the image-ID protection set from all existing containers and Compose images.
# Arguments: None.
# Output: Warnings when a Compose-resolved image is not present locally.
# Return status: 0 on success; Docker inspection failures propagate.
# Side effects: Populates global PROTECTED_IMAGE_IDS; Docker state is unchanged.
# External calls: docker ps/inspect/image inspect and docker compose config.
# Failures: Existing-container inspection errors stop execution; a missing Compose
#           image only warns because no deletion can target a nonexistent image.
protect_current_images() {
    local image_id image_ref
    local -a container_ids=()

    mapfile -t container_ids < <(docker ps -aq)
    if ((${#container_ids[@]})); then
        while IFS= read -r image_id; do
            [[ -n "$image_id" ]] && PROTECTED_IMAGE_IDS["$image_id"]=1
        done < <(docker inspect --format '{{.Image}}' "${container_ids[@]}" | sort -u)
    fi

    while IFS= read -r image_ref; do
        [[ -n "$image_ref" ]] || continue
        if image_id="$(docker image inspect "$image_ref" --format '{{.Id}}' 2>/dev/null)"; then
            PROTECTED_IMAGE_IDS["$image_id"]=1
        else
            printf 'WARNING: Compose image is not local: %s\n' "$image_ref" >&2
        fi
    done < <(docker compose config --images | sort -u)
}

# Classify Docker repositories that are in scope for automatic image cleanup.
# Arguments: $1 - Repository name from `docker image ls`.
# Output: None.
# Return status: 0 for recognized Immich/Valkey repositories; 1 otherwise.
# Side effects: None.
# Failures: None; unknown repositories are deliberately out of scope.
is_stack_repository() {
    case "$1" in
        ghcr.io/immich-app/immich-server|\
        ghcr.io/immich-app/immich-machine-learning|\
        ghcr.io/immich-app/postgres|\
        valkey/valkey|\
        docker.io/valkey/valkey)
            return 0 ;;
        *) return 1 ;;
    esac
}

# Remove unprotected old Immich/Valkey images and optionally all dangling images.
# Arguments: None; uses APPLY, PRUNE_DANGLING and PROTECTED_IMAGE_IDS globals.
# Output: WOULD DELETE/DELETE/KEEP lines and dangling-prune scope notice.
# Return status: 0 on success; Docker enumeration/removal errors propagate.
# Side effects: With --apply, deletes unprotected images from recognized stack
#               repositories. With --prune-dangling, also deletes any unprotected
#               dangling image on the host, including non-Immich images.
# External calls: docker image ls and docker image rm.
# Failures: Active/current Compose images are protected; removal failures stop the
#           script instead of being silently ignored.
cleanup_docker_images() {
    local image_id repository tag image_ref found=false

    printf '%s\n' '=== OBSOLETE IMMICH-STACK IMAGES ==='
    while IFS='|' read -r image_id repository tag; do
        [[ -n "$image_id" ]] || continue
        [[ -z "${PROTECTED_IMAGE_IDS[$image_id]+x}" ]] || continue
        is_stack_repository "$repository" || continue
        found=true
        [[ "$tag" == "<none>" ]] && image_ref="$image_id" || image_ref="${repository}:${tag}"

        if [[ "$APPLY" == true ]]; then
            printf 'DELETE: %s\n' "$image_ref"
            docker image rm "$image_ref"
        else
            printf 'WOULD DELETE: %s\n' "$image_ref"
        fi
    done < <(docker image ls --no-trunc --format '{{.ID}}|{{.Repository}}|{{.Tag}}')
    [[ "$found" == true ]] || printf '%s\n' 'None.'

    printf '%s\n' '=== DANGLING IMAGES ==='
    if [[ "$PRUNE_DANGLING" != true ]]; then
        printf '%s\n' 'Skipped. Use --prune-dangling to include unused dangling images.'
        return 0
    fi

    found=false
    while IFS= read -r image_id; do
        [[ -n "$image_id" ]] || continue
        if [[ -n "${PROTECTED_IMAGE_IDS[$image_id]+x}" ]]; then
            printf 'KEEP (protected): %s\n' "$image_id"
            continue
        fi
        found=true
        if [[ "$APPLY" == true ]]; then
            printf 'DELETE: %s\n' "$image_id"
            docker image rm "$image_id"
        else
            printf 'WOULD DELETE: %s\n' "$image_id"
        fi
    done < <(docker image ls --no-trunc --filter dangling=true --format '{{.ID}}' | sort -u)
    [[ "$found" == true ]] || printf '%s\n' 'None.'
}

# Print the final operational state after dry-run or cleanup.
# Arguments: None.
# Output: Compose status, remaining images, Docker disk usage and `df -h /`.
# Return status: 0 on success; reporting command failures propagate.
# Side effects: None; all invoked commands are read-only.
# External calls: docker compose ps, docker image ls, docker system df and df.
# Failures: A report failure stops the script so incomplete validation is not
#           presented as a successful cleanup.
report_state() {
    printf '\n%s\n' '=== CURRENT COMPOSE STATUS ==='
    docker compose ps
    printf '\n%s\n' '=== CURRENT IMAGES ==='
    docker image ls --format 'table {{.Repository}}\t{{.Tag}}\t{{.ID}}\t{{.CreatedSince}}\t{{.Size}}'
    printf '\n%s\n' '=== DOCKER DISK USAGE ==='
    docker system df
    printf '\n%s\n' '=== FILESYSTEM ==='
    df -h /
    printf '\n%s\n' 'Docker volumes were not touched; the Immich ML model cache is preserved.'
}

# Coordinate argument parsing, safety validation, cleanup and final reporting.
# Arguments: $@ - Raw CLI tokens passed to parse_args.
# Output: Complete dry-run plan or applied-action log followed by state report.
# Return status: 0 on success; 2 for invalid CLI; 1/command status for validation
#                or operational failures.
# Side effects: Delegates documented deletion behavior to cleanup functions only
#               when --apply is supplied.
# Failures: Any uncaught failure terminates execution because strict mode is active.
main() {
    parse_args "$@"
    validate_environment

    [[ "$APPLY" == true ]] \
        && printf '%s\n' 'MODE: APPLY' \
        || printf '%s\n' 'MODE: DRY-RUN (nothing will be deleted)'
    printf 'PROJECT: %s\nBACKUPS: %s/%s\n\n' "$PROJECT_DIR" "$BACKUP_ROOT" "$BACKUP_PATTERN"

    validate_runtime_state
    cleanup_upgrade_backups
    printf '\n'
    cleanup_env_backups
    printf '\n'
    protect_current_images
    cleanup_docker_images
    report_state

    if [[ "$APPLY" == true ]]; then
        printf '\n%s\n' 'Cleanup completed.'
    else
        printf '\n%s\n' 'Dry-run completed. Re-run with --apply after reviewing the plan.'
    fi
}

main "$@"
