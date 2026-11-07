"""Exercise the paid Stripe order, a Rattaproff euro invoice, and a kit delivery, then roll back.

Run from `odoo shell`. This script never commits.
"""

PAYLOAD = {
    "id": 900001,
    "number": "900001",
    "status": "processing",
    "date_paid": "2026-11-07T12:00:00",
    "payment_method": "stripe",
    "payment_method_title": "Stripe",
    "currency": "HUF",
    "billing": {
        "first_name": "Test",
        "last_name": "Stripe",
        "email": "stripe-test@example.com",
        "address_1": "Teszt utca 2.",
        "city": "Budapest",
        "postcode": "1052",
        "country": "HU",
    },
    "line_items": [{
        "sku": "M-001",
        "quantity": 1,
        "total": "10000.00",
        "name": "Blurby Trekking",
    }],
}


def on_hand(product):
    quants = env["stock.quant"].search([
        ("product_id", "=", product.id),
        ("location_id.usage", "=", "internal"),
    ])
    return sum(quants.mapped("quantity"))


def main():
    company = env.company
    if company.name != "Hagen Group Kft.":
        raise SystemExit(f"company name is {company.name!r}")
    if company.vat != "25979923-2-41":
        raise SystemExit(f"vat is {company.vat!r}")
    if company.company_registry != "01-09-299788":
        raise SystemExit(f"registry is {company.company_registry!r}")
    if company.street != "Kecskeméti utca 5." or company.zip != "1053":
        raise SystemExit(f"seat changed: {company.zip} {company.street}")
    if company.l10n_hu_edi_server_mode != "demo":
        raise SystemExit(f"NAV mode is {company.l10n_hu_edi_server_mode!r}")
    if env["account.move"].search_count([("ref", "=", "BLURBY-SAMPLE-DRAFT")]):
        raise SystemExit("sample invoice is still there")
    if env["res.partner"].search_count([("name", "=", "Sample customer (delete me)")]):
        raise SystemExit("sample customer is still there")

    journal = env["account.journal"].search([
        ("code", "=", "STRP"),
        ("company_id", "=", company.id),
        ("name", "=", "Stripe Payments"),
        ("type", "=", "bank"),
    ], limit=1)
    if not journal:
        raise SystemExit("Stripe Payments journal is missing")

    for module_name in ("mrp", "hagen_commerce"):
        module = env["ir.module.module"].search([("name", "=", module_name), ("state", "=", "installed")], limit=1)
        if not module:
            raise SystemExit(f"{module_name} is not installed")

    stores = env["hagen.woo.store"].with_context(active_test=False).search([])
    if len(stores) < 2:
        raise SystemExit(f"expected two WooCommerce stores, found {len(stores)}")

    bike = env["product.product"].search([("default_code", "=", "M-001")], limit=1)
    part = env["product.product"].search([("default_code", "=", "A34")], limit=1)
    if not bike.is_storable or not part.is_storable:
        raise SystemExit("bike or part is not a storable product")

    store = stores.filtered(lambda row: row.name == "Blurby store")[:1]
    order = store._import_paid_order(PAYLOAD)
    if order.state != "sale":
        raise SystemExit(f"sales order state is {order.state}")
    invoice = order.invoice_ids.filtered(lambda move: move.move_type == "out_invoice" and move.state == "posted")[:1]
    if not invoice:
        raise SystemExit(f"posted invoice missing, states={order.invoice_ids.mapped('state')}")
    if abs(invoice.amount_untaxed - 10000) > 0.02 or abs(invoice.amount_tax - 2700) > 0.02:
        raise SystemExit(
            f"tax math failed: untaxed={invoice.amount_untaxed} tax={invoice.amount_tax} total={invoice.amount_total}"
        )
    if invoice.payment_state != "paid":
        raise SystemExit(f"invoice payment state is {invoice.payment_state}")
    if invoice.l10n_hu_edi_state:
        raise SystemExit(f"NAV state was set: {invoice.l10n_hu_edi_state}")
    payment = env["account.payment"].search([
        ("journal_id", "=", journal.id),
        ("partner_id", "=", order.partner_id.id),
    ], limit=1)
    if not payment:
        raise SystemExit("Stripe payment was not registered")

    shop = env["hagen.woo.store"].with_context(active_test=False).search([
        ("base_url", "=", "https://rattaproff.ee"),
    ], limit=1)
    if not shop or shop.stock_sync or not shop.network_id:
        raise SystemExit(f"Rattaproff shop is not ready: {shop}")
    euro = env.ref("base.EUR")
    converted = euro._convert(1.0, company.currency_id, company, "2026-11-07")
    if converted < 300 or converted > 450:
        raise SystemExit(f"EUR rate looks wrong: 1 EUR = {converted} HUF")
    foreign = shop._import_paid_order({
        "id": 900002,
        "number": "900002",
        "status": "processing",
        "date_paid": "2026-11-07T12:00:00",
        "payment_method": "stripe",
        "payment_method_title": "MasterCard",
        "currency": "EUR",
        "billing": {
            "first_name": "Test",
            "last_name": "Rattaproff",
            "email": "rattaproff-test@example.com",
            "address_1": "Teszt 1",
            "city": "Tallinn",
            "postcode": "10111",
            "country": "EE",
        },
        "shipping_total": "4.02",
        "shipping_tax": "0.96",
        "tax_lines": [{"rate_id": 1, "rate_percent": 24, "tax_total": "2.85"}],
        "line_items": [{
            "sku": "155883_KVED",
            "name": "Test glue",
            "quantity": 1,
            "total": "7.89",
            "total_tax": "1.89",
            "taxes": [{"id": 1, "total": "1.89"}],
        }],
    })
    if foreign.currency_id.name != "EUR":
        raise SystemExit(f"Rattaproff currency is {foreign.currency_id.name}")
    foreign_invoice = foreign.invoice_ids.filtered(lambda move: move.state == "posted")[:1]
    if not foreign_invoice:
        raise SystemExit("Rattaproff invoice was not posted")
    if abs(foreign_invoice.amount_untaxed - 11.91) > 0.05 or abs(foreign_invoice.amount_tax - 2.85) > 0.05:
        raise SystemExit(
            f"Rattaproff tax math failed: untaxed={foreign_invoice.amount_untaxed} "
            f"tax={foreign_invoice.amount_tax} total={foreign_invoice.amount_total}"
        )
    if foreign_invoice.payment_state != "paid" or foreign_invoice.l10n_hu_edi_state:
        raise SystemExit(
            f"Rattaproff payment/NAV unexpected: {foreign_invoice.payment_state} {foreign_invoice.l10n_hu_edi_state}"
        )
    glue = env["product.product"].search([("default_code", "=", "155883_KVED")], limit=1)
    if not glue or glue.is_storable:
        raise SystemExit("unknown Rattaproff SKU should be a non-stock product")

    start = on_hand(part)
    env["mrp.bom"].create({
        "product_tmpl_id": bike.product_tmpl_id.id,
        "product_id": bike.id,
        "product_qty": 1.0,
        "type": "phantom",
        "company_id": company.id,
        "bom_line_ids": [(0, 0, {"product_id": part.id, "product_qty": 1.0})],
    })
    partner = env["res.partner"].create({"name": "Kit deduction test", "country_id": env.ref("base.hu").id})
    sale = env["sale.order"].create({"partner_id": partner.id, "company_id": company.id})
    line = env["sale.order.line"].create({
        "order_id": sale.id,
        "product_id": bike.id,
        "product_uom_qty": 1,
    })
    line.price_unit = 1.0
    sale.action_confirm()
    picking = sale.picking_ids[:1]
    if not picking:
        raise SystemExit("kit sale created no delivery")
    if part not in picking.move_ids.product_id:
        raise SystemExit(f"delivery did not explode into parts: {picking.move_ids.mapped('product_id.default_code')}")
    for move in picking.move_ids:
        move.quantity = move.product_uom_qty
        move.picked = True
    result = picking.button_validate()
    if isinstance(result, dict) and result.get("res_model"):
        wizard = env[result["res_model"]].with_context(**(result.get("context") or {})).create({})
        if hasattr(wizard, "process"):
            wizard.process()
        elif hasattr(wizard, "process_cancel_backorder"):
            wizard.process_cancel_backorder()
        else:
            raise SystemExit(f"unhandled validation wizard {result['res_model']}")
    picking.invalidate_recordset()
    if picking.state != "done":
        raise SystemExit(f"delivery state is {picking.state}")
    deducted = start - on_hand(part)
    if abs(deducted - 1) > 1e-6:
        raise SystemExit(f"A34 deduction was {deducted}, expected 1")

    print(
        "HAGEN FLOW OK",
        company.name,
        journal.code,
        f"invoice={invoice.amount_untaxed}+{invoice.amount_tax}={invoice.amount_total}",
        f"payment={invoice.payment_state}",
        f"nav={company.l10n_hu_edi_server_mode}",
        f"rattaproff={foreign_invoice.amount_total} {foreign_invoice.currency_id.name}",
        f"eur={converted:.2f}",
        f"kit_deducted={deducted}",
    )


if "env" not in globals():
    raise SystemExit("check_hagen_flow.py must be run from odoo shell")

try:
    main()
finally:
    env.cr.rollback()
