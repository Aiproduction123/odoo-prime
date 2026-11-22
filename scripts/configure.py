"""Company, chart, catalog, and removal of the sample draft invoice.

Executed inside `odoo shell`, which provides `env` and `stage`.
`stage` is either "company" (before Accounting is installed) or "books".
"""

import os
import sys

sys.path.insert(0, "/opt/blurby")

import catalog_data  # noqa: E402

COMPANY_NAME = "Hagen Group Kft."
VAT = "25979923-2-43"
REGISTRY = "01-09-299788"
SAMPLE_REF = "BLURBY-SAMPLE-DRAFT"


def commit():
    env.cr.commit()


def company_stage():
    company = env.company
    hungary = env.ref("base.hu")
    forint = env.ref("base.HUF")
    if company.currency_id != forint:
        company.currency_id = forint
    company.write({
        "name": COMPANY_NAME,
        "street": "Öntő utca 5.",
        "street2": False,
        "zip": "1211",
        "city": "Budapest",
        "country_id": hungary.id,
        "email": "info@blurbybike.com",
        "company_registry": REGISTRY,
        "vat": VAT,
    })
    print("COMPANY READY", company.name, company.country_id.code, company.currency_id.name)
    commit()


def chart_tax(company, xmlid):
    tax = env["account.chart.template"].with_company(company).ref(xmlid, raise_if_not_found=False)
    if not tax:
        raise SystemExit(f"Hungarian tax {xmlid} was not created")
    return tax


def category(name):
    record = env["product.category"].search([("name", "=", name)], limit=1)
    if not record:
        record = env["product.category"].create({"name": name})
    return record


def note(manufacturer, model, unit, price_note):
    lines = []
    if manufacturer:
        lines.append(f"Manufacturer: {manufacturer}")
    if model:
        lines.append(f"Model: {model}")
    if unit:
        lines.append(f"Inventory unit on the sheet: {unit}")
    lines.append(price_note)
    return "\n".join(lines)


def upsert_product(code, name, categ, description, sale_tax, purchase_tax, storable):
    template = env["product.template"].search([("default_code", "=", code)], limit=1)
    vals = {
        "name": name,
        "default_code": code,
        "categ_id": categ.id,
        "description": description,
        "list_price": 0.0,
        "sale_ok": True,
        "purchase_ok": True,
        "taxes_id": [(6, 0, sale_tax.ids)],
        "supplier_taxes_id": [(6, 0, purchase_tax.ids)],
        "invoice_policy": "order",
    }
    if storable:
        if "is_storable" in env["product.template"]._fields:
            vals["type"] = "consu"
            vals["is_storable"] = True
        else:
            vals["type"] = "product"
    else:
        vals["type"] = "service"
        if "is_storable" in env["product.template"]._fields:
            vals["is_storable"] = False
    if template:
        template.write(vals)
    else:
        template = env["product.template"].create(vals)
    return template.product_variant_id


def set_on_hand(product, location, quantity):
    if quantity <= 0:
        return
    Quant = env["stock.quant"]
    current = Quant._get_available_quantity(product, location)
    if abs(current - quantity) < 1e-6:
        return
    quant = Quant.with_context(inventory_mode=True).search([
        ("product_id", "=", product.id),
        ("location_id", "=", location.id),
    ], limit=1)
    if not quant:
        quant = Quant.with_context(inventory_mode=True).create({
            "product_id": product.id,
            "location_id": location.id,
        })
    quant = quant.with_context(inventory_mode=True)
    quant.inventory_quantity = quantity
    quant.action_apply_inventory()


def books_stage():
    company = env.company
    if company.chart_template != "hu":
        env["account.chart.template"].try_loading("hu", company, install_demo=False)
    company = env.company
    if company.chart_template != "hu":
        raise SystemExit(f"chart template is {company.chart_template!r}, expected hu")

    company.with_context(no_vat_validation=False).write({"vat": VAT})
    if company.vat != VAT:
        raise SystemExit(f"VAT stored as {company.vat!r}, expected {VAT}")

    company.company_details = (
        "<p>Hagen Group Kft.<br/>"
        "1211 Budapest, Öntő utca 5.<br/>"
        "Cégjegyzékszám: 01-09-299788<br/>"
        "Adószám: 25979923-2-43<br/>"
        "info@blurbybike.com</p>"
    )
    if "l10n_hu_edi_server_mode" in company._fields:
        # Demo mocks NAV. Nothing is filed until you switch this to
        # production and save the technical-user keys.
        company.l10n_hu_edi_server_mode = "demo"
    if hasattr(company, "_l10n_hu_edi_configure_company"):
        company._l10n_hu_edi_configure_company()

    hungarian = env["res.lang"].search([("code", "=", "hu_HU"), ("active", "=", True)], limit=1)
    if hungarian:
        company.partner_id.lang = "hu_HU"

    workshop = env["res.partner"].search([
        ("name", "in", ["Blurby workshop", "Hagen Group workshop"]),
        ("parent_id", "=", company.partner_id.id),
    ], limit=1)
    if workshop:
        workshop.name = "Hagen Group workshop"
    else:
        env["res.partner"].create({
            "name": "Hagen Group workshop",
            "type": "delivery",
            "parent_id": company.partner_id.id,
            "street": "Öntő utca 5.",
            "zip": "1211",
            "city": "Budapest",
            "country_id": env.ref("base.hu").id,
            "email": "info@blurbybike.com",
            "comment": "Service workshop at the registered seat.",
        })

    goods_sale = chart_tax(company, "F27")
    goods_purchase = chart_tax(company, "V27")
    service_sale = chart_tax(company, "F27S")
    service_purchase = chart_tax(company, "V27S")
    price_note = "Sale price is not set. Put the real price on the product before invoicing."

    for code, name, categ_name, manufacturer, model, quantity, unit in catalog_data.PARTS:
        upsert_product(
            code,
            name,
            category(categ_name),
            note(manufacturer, model, unit, price_note),
            goods_sale,
            goods_purchase,
            storable=True,
        )

    for code, name in catalog_data.BIKES:
        upsert_product(
            code,
            name,
            category("Bikes"),
            price_note,
            goods_sale,
            goods_purchase,
            storable=True,
        )

    upsert_product(
        "SVC-LABOUR",
        "Workshop labour",
        category("Services"),
        "Workshop time at Öntő utca. Sale price is not set.",
        service_sale,
        service_purchase,
        storable=False,
    )

    commit()
    warehouse = env["stock.warehouse"].search([("company_id", "=", company.id)], limit=1)
    if not warehouse:
        raise SystemExit("Inventory warehouse was not created")
    location = warehouse.lot_stock_id
    failures = []
    for code, _name, _categ, _manufacturer, _model, quantity, _unit in catalog_data.PARTS:
        product = env["product.product"].search([("default_code", "=", code)], limit=1)
        try:
            set_on_hand(product, location, quantity)
            commit()
        except Exception as error:  # noqa: BLE001 - one bad line should not discard the catalog
            env.cr.rollback()
            failures.append(f"{code}: {error}")
            print("STOCK SKIP", code, error)
    if failures:
        raise SystemExit("stock adjustments failed:\n" + "\n".join(failures[:12]))

    part_count = env["product.template"].search_count([("default_code", "=like", "A%")])
    if part_count < 153:
        raise SystemExit(f"expected 153 parts, found {part_count}")

    cells = env["product.product"].search([("default_code", "=", "A27")], limit=1)
    on_hand = env["stock.quant"]._get_available_quantity(cells, location)
    if abs(on_hand - 935) > 1e-6:
        raise SystemExit(f"A27 on hand is {on_hand}, expected 935")

    sample_invoices = env["account.move"].search([
        ("ref", "=", SAMPLE_REF),
        ("state", "=", "draft"),
        ("company_id", "=", company.id),
    ])
    sample_invoices.unlink()
    sample_partners = env["res.partner"].search([("name", "=", "Sample customer (delete me)")])
    for partner in sample_partners:
        if not env["account.move"].search_count([("partner_id", "=", partner.id)]):
            partner.unlink()

    english = env["res.lang"].with_context(active_test=False).search([("code", "=", "en_US")], limit=1)
    if english and not english.active:
        english.active = True
    password = os.environ.get("BLURBY_ADMIN_PASSWORD")
    if not password:
        raise SystemExit("BLURBY_ADMIN_PASSWORD is empty")
    admin = env.ref("base.user_admin")
    admin.write({
        "name": "Ivari Kull",
        "login": "ivari",
        "email": "ivari@blurbybike.com",
        "tz": "Europe/Berlin",
        "lang": "en_US",
    })
    admin.password = password

    # Fallback for jobs that have no browser. A laptop on localhost and an
    # office computer on the network address each keep the host they opened.
    env["ir.config_parameter"].set_param("web.base.url", "http://127.0.0.1:18469")
    env["ir.config_parameter"].set_param("web.base.url.freeze", "False")
    env["ir.config_parameter"].set_param("blurby.setup_version", "1")
    commit()
    print(
        "SETUP OK",
        company.name,
        company.vat,
        company.chart_template,
        company.l10n_hu_edi_server_mode,
        f"parts={part_count}",
    )


if "env" not in globals():
    raise SystemExit("configure.py must be run from odoo shell")
if stage == "company":
    company_stage()
elif stage == "books":
    books_stage()
else:
    raise SystemExit(f"unknown stage {stage!r}")
