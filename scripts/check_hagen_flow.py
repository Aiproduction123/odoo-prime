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
    if company.vat != "25979923-2-43":
        raise SystemExit(f"vat is {company.vat!r}")
    if company.company_registry != "01-09-299788":
        raise SystemExit(f"registry is {company.company_registry!r}")
    if company.street != "Öntő utca 5." or company.zip != "1211":
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
    if len(stores) < 23:
        raise SystemExit(f"expected 23 WooCommerce stores, found {len(stores)}")
    blurby_hu = stores.filtered(lambda row: row.name == "Blurby HU store")[:1]
    if not blurby_hu or blurby_hu.base_url != "https://blurbybike.hu" or not blurby_hu.stock_sync or blurby_hu.network_id:
        raise SystemExit(f"Blurby HU store is not a stock master: {blurby_hu}")

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

    other = store._import_paid_order({
        **PAYLOAD,
        "id": 900003,
        "number": "900003",
        "payment_method": "bacs",
        "payment_method_title": "Direct bank transfer",
        "billing": {**PAYLOAD["billing"], "email": "bank-test@example.com"},
    })
    other_invoice = other.invoice_ids.filtered(lambda move: move.state == "posted")[:1]
    if not other_invoice or other_invoice.payment_state != "not_paid" or abs(other_invoice.amount_tax - 2700) > 0.02:
        raise SystemExit(f"bank transfer order should be invoiced and open: {other_invoice.payment_state}")

    # hagenbikes.com configurator lines carry the drive type in their options, not a SKU.
    def line(name, *options):
        return {"name": name, "sku": "", "meta_data": [
            {"key": f"pa_{i}", "display_key": label, "display_value": value} for i, (label, value) in enumerate(options)
        ]}
    cases = [
        (line("Hagen XL", ("01 Colors", "Black"), ("02 Type", "90 Nm Brose Mid-Motor (+ 3100.00 €)")), "M-008"),
        (line("Hagen FLAGSHIP", ("01 Colors", "Yellow"), ("02 Type", "Non-electric")), "M-005"),
        (line("Hagen FLAGSHIP", ("02 Farben", "Weiß"), ("01 Typ", "Nicht-elektrisch")), "M-005"),
        (line("Hagen FLAGSHIP", ("01 Colors", "Black"), ("02 Type", "90 Nm Brose Mid-Motor")), "M-006"),
        (line("Hagen XL", ("02 Type", "Non-electric (+ 0.00 €)")), "M-007"),
        (line("Hagen FLAGSHIP", ("01 Colors", "Yellow"), ("02 Type", "Frame set"), ("04 Handlebar", "Flat")), "FS-HAGEN-FLAGSHIP"),
        (line("Hagen XL", ("02 Type", "Frame set electric")), "FS-HAGEN-XL"),
        (line("Hagen MINI", ("02 Type", "Frame set")), None),
        (line("Canopy"), None),
    ]
    for item, expected in cases:
        got = store._configured_code(item)
        if got != expected:
            raise SystemExit(f"configurator mapping {item['name']} {item['meta_data']} -> {got}, expected {expected}")
    hagen_store = stores.filtered(lambda row: row.name == "Hagen store")[:1]
    configured = hagen_store._import_paid_order({
        **PAYLOAD,
        "id": 900004,
        "number": "6447",
        "currency": "EUR",
        "billing": {**PAYLOAD["billing"], "email": "config-test@example.com", "country": "BE"},
        "line_items": [{**cases[0][0], "quantity": 1, "total": "4390.00", "product_id": 172}],
    })
    if configured.order_line[:1].product_id.default_code != "M-008":
        raise SystemExit(f"configurator order mapped to {configured.order_line.product_id.mapped('default_code')}")

    # Kit delivery: the Hagen XL frameset ships as frame, fork, bearings, kickstand and steering rod.
    frameset = env["product.product"].search([("default_code", "=", "FS-HAGEN-XL")], limit=1)
    fork = env["product.product"].search([("default_code", "=", "A65")], limit=1)
    bearing = env["product.product"].search([("default_code", "=", "A96")], limit=1)
    part = env["product.product"].search([("default_code", "=", "A63")], limit=1)
    stock_location = env["stock.warehouse"].search([("company_id", "=", company.id)], limit=1).lot_stock_id
    kit = env["mrp.bom"]._bom_find(frameset, bom_type="phantom")[frameset]
    for kit_line in kit.bom_line_ids:
        shortfall = kit_line.product_qty - on_hand(kit_line.product_id)
        if shortfall > 0:
            env["stock.quant"]._update_available_quantity(kit_line.product_id, stock_location, shortfall)
    fork_start, bearing_start = on_hand(fork), on_hand(bearing)
    start = on_hand(part)
    partner = env["res.partner"].create({"name": "Kit deduction test", "country_id": env.ref("base.hu").id})
    sale = env["sale.order"].create({"partner_id": partner.id, "company_id": company.id})
    line = env["sale.order.line"].create({
        "order_id": sale.id,
        "product_id": frameset.id,
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
    if abs(deducted - 1) > 1e-6 or fork_start - on_hand(fork) != 1 or bearing_start - on_hand(bearing) != 4:
        raise SystemExit(f"A63 deduction was {deducted}, fork {on_hand(fork)}, bearings {on_hand(bearing)}")

    print(
        "HAGEN FLOW OK",
        company.name,
        journal.code,
        f"invoice={invoice.amount_untaxed}+{invoice.amount_tax}={invoice.amount_total}",
        f"payment={invoice.payment_state}",
        f"bank_transfer={other_invoice.payment_state}",
        f"configurator={configured.order_line[:1].product_id.default_code}",
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
