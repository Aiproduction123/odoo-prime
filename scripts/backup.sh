#!/usr/bin/env bash
# Dump the blurby database and the Odoo filestore into backups/.
# Bash 3.2 / macOS: no associative arrays, no GNU sed, no mapfile.
# Does not print passwords. Dumps stay out of git (see .gitignore).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if docker info >/dev/null 2>&1; then
  COMPOSE=(docker compose)
else
  COMPOSE=(sudo docker compose)
fi

keep="${BACKUP_KEEP:-14}"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --keep)
      shift
      keep="${1:-}"
      ;;
    --keep=*)
      keep="${1#--keep=}"
      ;;
    -h|--help)
      echo "Usage: ./scripts/backup.sh [--keep N]"
      echo "Writes backups/blurby-YYYYmmdd-HHMMSS.dump and the matching -filestore.tar.gz."
      echo "Keeps the newest N pairs (default 14, or BACKUP_KEEP)."
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      exit 1
      ;;
  esac
  shift
done

case "$keep" in
  ''|*[!0-9]*)
    echo "Keep count must be a positive number." >&2
    exit 1
    ;;
esac
if [[ "$keep" -lt 1 ]]; then
  echo "Keep count must be at least 1." >&2
  exit 1
fi

if [[ ! -f .env ]]; then
  echo "Missing .env. Run ./scripts/bootstrap.sh first." >&2
  exit 1
fi

# Compose reads .env itself. Sourcing checks the file is readable without echoing it.
set -a
# shellcheck disable=SC1091
source .env
set +a
if [[ -z "${POSTGRES_PASSWORD:-}" ]]; then
  echo "POSTGRES_PASSWORD is empty in .env." >&2
  exit 1
fi

mkdir -p backups
chmod 700 backups
umask 077

stamp="$(date +%Y%m%d-%H%M%S)"
dump="$ROOT/backups/blurby-${stamp}.dump"
archive="$ROOT/backups/blurby-${stamp}-filestore.tar.gz"

echo "Starting Postgres"
"${COMPOSE[@]}" up -d --wait db

odoo_running=0
state="$("${COMPOSE[@]}" ps --format '{{.State}}' odoo 2>/dev/null | head -n 1 || true)"
if [[ "$state" == "running" ]]; then
  odoo_running=1
  echo "Stopping Odoo for a consistent copy"
  "${COMPOSE[@]}" stop odoo
fi

restart_odoo() {
  if [[ "$odoo_running" -eq 1 ]]; then
    echo "Starting Odoo"
    "${COMPOSE[@]}" up -d odoo
    odoo_running=0
  fi
}

dump_ok=0
archive_ok=0
cleanup() {
  status=$?
  if [[ "$dump_ok" -ne 1 ]]; then
    rm -f "$dump"
  fi
  if [[ "$archive_ok" -ne 1 ]]; then
    rm -f "$archive"
  fi
  restart_odoo
  exit "$status"
}
trap cleanup EXIT

# Password stays inside the db container (POSTGRES_PASSWORD from .env). -Fc is a custom dump.
echo "Dumping database blurby"
if ! "${COMPOSE[@]}" exec -T db sh -c 'PGPASSWORD="$POSTGRES_PASSWORD" pg_dump --no-password -Fc -U odoo -d blurby' > "$dump"; then
  echo "Database dump failed." >&2
  exit 1
fi
dump_bytes="$(wc -c < "$dump" | tr -d '[:space:]')"
if [[ "$dump_bytes" -lt 1000 ]]; then
  echo "Database dump is too small to be a blurby backup." >&2
  exit 1
fi
dump_ok=1
chmod 600 "$dump"

# blurby-data is mounted on the odoo service at /var/lib/odoo.
echo "Archiving filestore volume blurby-data"
if ! "${COMPOSE[@]}" run --rm --no-deps -T --user root --entrypoint tar odoo -C /var/lib/odoo -czf - . > "$archive"; then
  echo "Filestore archive failed." >&2
  exit 1
fi
archive_bytes="$(wc -c < "$archive" | tr -d '[:space:]')"
if [[ "$archive_bytes" -lt 100 ]]; then
  echo "Filestore archive is too small." >&2
  exit 1
fi
archive_ok=1
chmod 600 "$archive"

echo "Wrote backups/blurby-${stamp}.dump"
echo "Wrote backups/blurby-${stamp}-filestore.tar.gz"

# Drop older pairs. Sort is chronological because the stamp is YYYYmmdd-HHMMSS.
kept=0
removed=0
# shellcheck disable=SC2012
older="$(ls -1 "$ROOT/backups"/blurby-*.dump 2>/dev/null | sort -r || true)"
if [[ -n "$older" ]]; then
  while IFS= read -r old_dump; do
    [[ -n "$old_dump" ]] || continue
    kept=$((kept + 1))
    if [[ "$kept" -le "$keep" ]]; then
      continue
    fi
    old_base="$(basename "$old_dump" .dump)"
    rm -f "$old_dump" "$ROOT/backups/${old_base}-filestore.tar.gz"
    removed=$((removed + 1))
    echo "Removed old backup ${old_base}"
  done <<EOF
$older
EOF
fi
if [[ "$removed" -eq 0 ]]; then
  echo "Keeping the last ${keep} backups (${kept} present)."
else
  echo "Removed ${removed} old backup(s). Keeping ${keep}."
fi
