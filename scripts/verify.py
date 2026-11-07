#!/usr/bin/env python3
"""Check the running Blurby ledger from outside the containers."""

import sys
import urllib.request
import xmlrpc.client
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
URL = "http://127.0.0.1:18469"


def load_env():
    values = {}
    for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key] = value
    return values


def execute(models, uid, password, model, method, domain=None, **kwargs):
    return models.execute_kw("blurby", uid, password, model, method, [domain or []], kwargs)


def main():
    env = load_env()
    password = env["BLURBY_ADMIN_PASSWORD"]
    with urllib.request.urlopen(URL + "/web/login", timeout=60) as response:
        body = response.read().decode("utf-8", "replace")
        if response.status != 200 or "login" not in body.lower():
            raise SystemExit(f"login page failed: {response.status}")

    common = xmlrpc.client.ServerProxy(URL + "/xmlrpc/2/common", allow_none=True)
    uid = common.authenticate("blurby", "ivari", password, {})
    if not uid:
        raise SystemExit("could not sign in as ivari")
    models = xmlrpc.client.ServerProxy(URL + "/xmlrpc/2/object", allow_none=True)

    company = execute(
        models, uid, password, "res.company", "search_read",
        [("id", "=", 1)],
        fields=[
            "name", "vat", "city", "zip", "street", "company_registry",
            "chart_template", "currency_id", "email", "l10n_hu_edi_server_mode",
        ],
        limit=1,
    )[0]
    checks = {
        "name": company["name"] == "BLURBY Korlátolt Felelősségű Társaság",
        "vat": company["vat"] == "25979923-2-41",
        "registry": company["company_registry"] == "01-09-299788",
        "address": company["zip"] == "1053" and company["city"] == "Budapest" and company["street"] == "Kecskeméti utca 5.",
        "chart": company["chart_template"] == "hu",
        "currency": "HUF" in (company["currency_id"][1] or ""),
        "email": company["email"] == "info@blurbybike.com",
        "nav_mode": company["l10n_hu_edi_server_mode"] == "demo",
    }
    failed = [name for name, ok in checks.items() if not ok]
    if failed:
        raise SystemExit(f"company mismatch: {failed} {company}")

    modules = execute(
        models, uid, password, "ir.module.module", "search_read",
        [("name", "in", ["account", "l10n_hu", "l10n_hu_edi", "sale_management", "stock"]), ("state", "=", "installed")],
        fields=["name"],
    )
    installed = {row["name"] for row in modules}
    missing = {"account", "l10n_hu", "l10n_hu_edi", "sale_management", "stock"} - installed
    if missing:
        raise SystemExit(f"modules not installed: {sorted(missing)}")

    parts = execute(models, uid, password, "product.template", "search_count", [("default_code", "=like", "A%")])
    if parts < 153:
        raise SystemExit(f"expected 153 parts, found {parts}")

    quant = execute(
        models, uid, password, "stock.quant", "search_read",
        [("product_id.default_code", "=", "A27"), ("location_id.usage", "=", "internal")],
        fields=["quantity"],
        limit=1,
    )
    if not quant or abs(quant[0]["quantity"] - 935) > 1e-6:
        raise SystemExit(f"A27 quantity unexpected: {quant}")

    invoice = execute(
        models, uid, password, "account.move", "search_read",
        [("ref", "=", "BLURBY-SAMPLE-DRAFT")],
        fields=["state", "amount_untaxed", "amount_tax", "amount_total", "currency_id"],
        limit=1,
    )
    if not invoice:
        raise SystemExit("sample draft invoice is missing")
    row = invoice[0]
    if row["state"] != "draft" or abs(row["amount_tax"] - 2700) > 0.01 or abs(row["amount_total"] - 12700) > 0.01:
        raise SystemExit(f"sample invoice unexpected: {row}")

    print(
        "OK",
        company["name"],
        company["vat"],
        f"parts={parts}",
        f"sample={row['amount_untaxed']}+{row['amount_tax']}={row['amount_total']} {row['currency_id'][1]}",
    )


if __name__ == "__main__":
    try:
        main()
    except Exception as error:  # noqa: BLE001
        print("VERIFY FAILED", error, file=sys.stderr)
        raise
