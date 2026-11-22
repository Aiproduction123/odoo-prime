#!/usr/bin/env bash
# Replace the blurby database and filestore from a backup made by backup.sh.
# Usage: ./scripts/restore.sh [--yes] <timestamp-or-path>
# Bash 3.2 / macOS: no associative arrays, no GNU sed, no mapfile.
# Does not print passwords.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if docker info >/dev/null 2>&1; then
  COMPOSE=(docker compose)
else
  COMPOSE=(sudo docker compose)
fi

yes=0
target=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --yes|-y)
      yes=1
      ;;
    -h|--help)
      echo "Usage: ./scripts/restore.sh [--yes] <timestamp-or-path>"
      echo "Accepts a stamp (YYYYmmdd-HHMMSS), backups/blurby-<stamp>, or a .dump path."
      echo "Stops Odoo, replaces the database and filestore, then starts Odoo."
      exit 0
      ;;
    --)
      shift
      break
      ;;
    -*)
      echo "Unknown option: $1" >&2
      exit 1
      ;;
    *)
      if [[ -n "$target" ]]; then
        echo "Only one backup can be restored." >&2
        exit 1
      fi
      target="$1"
      ;;
  esac
  shift
done
if [[ $# -gt 0 ]]; then
  if [[ -n "$target" ]]; then
    echo "Only one backup can be restored." >&2
    exit 1
  fi
  target="$1"
fi

if [[ -z "$target" ]]; then
  echo "Usage: ./scripts/restore.sh [--yes] <timestamp-or-path>" >&2
  exit 1
fi

if [[ ! -f .env ]]; then
  echo "Missing .env. Run ./scripts/bootstrap.sh first." >&2
  exit 1
fi

set -a
# shellcheck disable=SC1091
source .env
set +a
if [[ -z "${POSTGRES_PASSWORD:-}" ]]; then
  echo "POSTGRES_PASSWORD is empty in .env." >&2
  exit 1
fi

resolve_dump() {
  local input="$1"
  local base
  if [[ -f "$input" ]]; then
    case "$input" in
      *.dump)
        printf '%s\n' "$input"
        return 0
        ;;
      *-filestore.tar.gz)
        printf '%s\n' "${input%-filestore.tar.gz}.dump"
        return 0
        ;;
    esac
  fi
  input="${input%/}"
  base="$(basename "$input")"
  base="${base%.dump}"
  base="${base%-filestore.tar.gz}"
  case "$base" in
    blurby-*) ;;
    *) base="blurby-${base}" ;;
  esac
  if [[ -f "$ROOT/backups/${base}.dump" ]]; then
    printf '%s\n' "$ROOT/backups/${base}.dump"
    return 0
  fi
  if [[ -f "${input}.dump" ]]; then
    printf '%s\n' "${input}.dump"
    return 0
  fi
  return 1
}

if ! dump="$(resolve_dump "$target")"; then
  echo "No backup dump found for: $target" >&2
  exit 1
fi
if [[ ! -f "$dump" ]]; then
  echo "Database dump is missing: $dump" >&2
  exit 1
fi
archive="${dump%.dump}-filestore.tar.gz"
if [[ ! -f "$archive" ]]; then
  echo "Filestore archive is missing: $archive" >&2
  exit 1
fi

stamp="$(basename "$dump" .dump)"
if [[ "$yes" -ne 1 ]]; then
  if [[ ! -t 0 ]]; then
    echo "Refusing to restore without a confirmation prompt. Re-run with --yes." >&2
    exit 1
  fi
  printf 'This replaces the blurby database and filestore with %s. Type yes to continue: ' "$stamp"
  read -r answer
  if [[ "$answer" != "yes" ]]; then
    echo "Restore cancelled."
    exit 1
  fi
fi

python3 scripts/render_config.py

echo "Starting Postgres"
"${COMPOSE[@]}" up -d --wait db

echo "Stopping Odoo"
"${COMPOSE[@]}" stop odoo >/dev/null 2>&1 || true

failed=1
trap 'if [[ "$failed" -eq 1 ]]; then echo "Restore failed. Odoo was left stopped." >&2; fi' EXIT

echo "Replacing database blurby"
"${COMPOSE[@]}" exec -T db sh -c 'PGPASSWORD="$POSTGRES_PASSWORD" psql --no-password -v ON_ERROR_STOP=1 -U odoo -d postgres -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '"'"'blurby'"'"' AND pid <> pg_backend_pid();"' >/dev/null
"${COMPOSE[@]}" exec -T db sh -c 'PGPASSWORD="$POSTGRES_PASSWORD" dropdb --no-password --if-exists -U odoo blurby'
"${COMPOSE[@]}" exec -T db sh -c 'PGPASSWORD="$POSTGRES_PASSWORD" createdb --no-password -U odoo -O odoo blurby'

# A fresh database already has schema public, so pg_restore may return 1 for that
# harmless notice. Any higher status, or a missing module table, is a failure.
set +e
"${COMPOSE[@]}" exec -T db sh -c 'PGPASSWORD="$POSTGRES_PASSWORD" pg_restore --no-password --no-owner --no-acl -U odoo -d blurby' < "$dump"
restore_status=$?
set -e
if [[ "$restore_status" -gt 1 ]]; then
  echo "pg_restore failed (status ${restore_status})." >&2
  exit 1
fi
module_state="$("${COMPOSE[@]}" exec -T db sh -c 'PGPASSWORD="$POSTGRES_PASSWORD" psql --no-password -U odoo -d blurby -tAc "SELECT state FROM ir_module_module WHERE name = '"'"'hagen_commerce'"'"'"' | tr -d '[:space:]')"
if [[ "$module_state" != "installed" ]]; then
  echo "Restored database has no installed hagen_commerce module (pg_restore status ${restore_status})." >&2
  exit 1
fi

echo "Replacing filestore volume blurby-data"
# The archive is extracted into /var/lib/odoo, the blurby-data mount, as root, then given to the odoo user.
"${COMPOSE[@]}" run --rm --no-deps -T --user root --entrypoint sh odoo -c 'find /var/lib/odoo -mindepth 1 -delete && tar -C /var/lib/odoo -xzf - && chown -R odoo:odoo /var/lib/odoo' < "$archive"

echo "Starting Odoo"
"${COMPOSE[@]}" up -d odoo
failed=0
echo "Restored ${stamp}"
