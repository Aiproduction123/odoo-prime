#!/usr/bin/env bash
# Create the Blurby database, load Hungarian invoicing, and start Odoo.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if docker info >/dev/null 2>&1; then
  COMPOSE=(docker compose)
else
  COMPOSE=(sudo docker compose)
fi

if [[ ! -f .env ]]; then
  python3 - <<'PY'
import secrets
from pathlib import Path
def password():
    return secrets.token_urlsafe(18)
Path(".env").write_text(
    "POSTGRES_PASSWORD=%s\nODOO_MASTER_PASSWORD=%s\nBLURBY_ADMIN_PASSWORD=%s\nHAGEN_EMPLOYEE_PASSWORD=%s\n" % (
        password(), password(), password(), password()
    ),
    encoding="utf-8",
)
os_chmod = Path(".env")
os_chmod.chmod(0o600)
print("Wrote .env with generated passwords")
PY
fi
if ! grep -q '^HAGEN_EMPLOYEE_PASSWORD=' .env; then
  python3 -c 'import secrets; print("HAGEN_EMPLOYEE_PASSWORD=" + secrets.token_urlsafe(18))' >> .env
fi
chmod 600 .env

set -a
# shellcheck disable=SC1091
source .env
set +a

python3 scripts/render_config.py

echo "Starting Postgres"
"${COMPOSE[@]}" up -d --wait db

db_exists() {
  local found
  found="$("${COMPOSE[@]}" exec -T db psql -U odoo -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname='blurby'" | tr -d '[:space:]')"
  [[ "$found" == "1" ]]
}

setup_version() {
  "${COMPOSE[@]}" exec -T db psql -U odoo -d blurby -tAc "SELECT value FROM ir_config_parameter WHERE key='blurby.setup_version'" 2>/dev/null | tr -d '[:space:]' || true
}

run_shell() {
  local stage="$1"
  "${COMPOSE[@]}" run --rm --no-deps -T odoo odoo shell -d blurby --no-http <<PY
stage = ${stage@Q}
exec(compile(open("/opt/blurby/configure.py", encoding="utf-8").read(), "/opt/blurby/configure.py", "exec"))
PY
}

version=""
if db_exists; then
  version="$(setup_version)"
fi

if [[ "${1:-}" == "--reconfigure" ]]; then
  version=""
fi

if ! db_exists; then
  echo "Creating the Odoo database"
  "${COMPOSE[@]}" run --rm --no-deps odoo odoo -d blurby -i base --without-demo=all --stop-after-init --load-language=hu_HU
fi

if [[ "$version" != "1" ]]; then
  echo "Writing the Hagen Group company"
  run_shell company
  echo "Installing invoicing, sales, inventory, and Hungarian localization"
  "${COMPOSE[@]}" run --rm --no-deps odoo odoo -d blurby -i sale_management,stock,l10n_hu,l10n_hu_edi --without-demo=all --stop-after-init
  echo "Loading the chart of accounts and parts"
  run_shell books
fi

if db_exists; then
  commerce="$("${COMPOSE[@]}" exec -T db psql -U odoo -d blurby -tAc "SELECT state FROM ir_module_module WHERE name='hagen_commerce'" 2>/dev/null | tr -d '[:space:]' || true)"
  if [[ "$commerce" != "installed" ]]; then
    echo "Installing manufacturing, purchase, and the WooCommerce connector"
    "${COMPOSE[@]}" stop odoo >/dev/null 2>&1 || true
    "${COMPOSE[@]}" run --rm --no-deps odoo odoo -d blurby -i purchase,hagen_commerce --without-demo=all --stop-after-init
  elif [[ "${1:-}" == "--upgrade" ]]; then
    echo "Upgrading the Hagen Group module"
    "${COMPOSE[@]}" stop odoo >/dev/null 2>&1 || true
    "${COMPOSE[@]}" run --rm --no-deps odoo odoo -d blurby -i purchase -u hagen_commerce --without-demo=all --stop-after-init
  fi
fi

echo "Starting Odoo"
"${COMPOSE[@]}" up -d odoo
echo "Odoo is starting on port 18469"
