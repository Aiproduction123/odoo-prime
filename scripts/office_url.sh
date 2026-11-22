#!/usr/bin/env bash
# Print the addresses other computers can use to open this Odoo.
set -euo pipefail

echo "On this computer: http://127.0.0.1:18469"
echo "Public URL (tunnel hagen-odoo -> http://odoo:8069): https://erp.hagenbikes.com"
if command -v ip >/dev/null 2>&1; then
  ip -4 -o addr show scope global | awk '{print $4}' | cut -d/ -f1 | while read -r addr; do
    case "$addr" in
      127.*|172.17.*|172.18.*) continue ;;
    esac
    echo "From another computer: http://${addr}:18469"
  done
elif command -v hostname >/dev/null 2>&1; then
  hostname -I | tr ' ' '\n' | while read -r addr; do
    [ -n "$addr" ] || continue
    case "$addr" in
      127.*|172.17.*|172.18.*) continue ;;
    esac
    echo "From another computer: http://${addr}:18469"
  done
fi
