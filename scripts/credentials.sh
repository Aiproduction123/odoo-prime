#!/usr/bin/env bash
# Load WooCommerce keys from .env into the blurby database.
# Stores stay inactive until Opening Inventory 2026 is applied.
# Bash 3.2 / macOS: no associative arrays, no GNU sed -i.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if docker info >/dev/null 2>&1; then
  COMPOSE=(docker compose)
else
  COMPOSE=(sudo docker compose)
fi

if [[ ! -f .env ]]; then
  echo "Missing .env. Run ./scripts/bootstrap.sh first, or copy .env.example to .env." >&2
  exit 1
fi

set -a
# shellcheck disable=SC1091
source .env
set +a

python3 scripts/render_config.py
"${COMPOSE[@]}" up -d --wait db

echo "Loading store credentials (shops stay off until Opening Inventory 2026)"
"${COMPOSE[@]}" run --rm --no-deps -T odoo odoo shell -d blurby --no-http <<'PY'
exec(compile(open("/opt/blurby/load_credentials.py", encoding="utf-8").read(), "/opt/blurby/load_credentials.py", "exec"))
PY
