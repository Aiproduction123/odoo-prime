#!/usr/bin/env python3
"""Check the running Hagen Group ledger from outside the containers."""

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
        "name": company["name"] == "Hagen Group Kft.",
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
        [("name", "in", ["account", "l10n_hu", "l10n_hu_edi", "sale_management", "stock", "mrp", "hagen_commerce"]), ("state", "=", "installed")],
        fields=["name"],
    )
    installed = {row["name"] for row in modules}
    missing = {"account", "l10n_hu", "l10n_hu_edi", "sale_management", "stock", "mrp", "hagen_commerce"} - installed
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

    leftover = execute(models, uid, password, "account.move", "search_count", [("ref", "=", "BLURBY-SAMPLE-DRAFT")])
    if leftover:
        raise SystemExit("sample draft invoice is still present")
    leftover_partner = execute(
        models, uid, password, "res.partner", "search_count",
        [("name", "=", "Sample customer (delete me)")],
    )
    if leftover_partner:
        raise SystemExit("sample customer is still present")

    journal = execute(
        models, uid, password, "account.journal", "search_read",
        [("code", "=", "STRP"), ("company_id", "=", 1)],
        fields=["name", "type"],
        limit=1,
    )
    if not journal or journal[0]["name"] != "Stripe Payments" or journal[0]["type"] != "bank":
        raise SystemExit(f"Stripe journal unexpected: {journal}")

    stores = execute(
        models, uid, password, "hagen.woo.store", "search_count",
        [],
        context={"active_test": False},
    )
    if stores < 2:
        raise SystemExit(f"expected two WooCommerce stores, found {stores}")

    bikes = execute(
        models, uid, password, "product.template", "search_read",
        [("default_code", "=like", "M-%")],
        fields=["default_code", "is_storable", "type"],
    )
    if len(bikes) < 8 or any(not row["is_storable"] or row["type"] != "consu" for row in bikes):
        raise SystemExit(f"bikes are not all storable: {bikes}")

    print(
        "OK",
        company["name"],
        company["vat"],
        company["l10n_hu_edi_server_mode"],
        f"parts={parts}",
        f"stores={stores}",
        "journal=STRP",
    )


if __name__ == "__main__":
    try:
        main()
    except Exception as error:  # noqa: BLE001
        print("VERIFY FAILED", error, file=sys.stderr)
        raise
