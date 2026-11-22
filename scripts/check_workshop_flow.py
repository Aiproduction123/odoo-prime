"""Exercise the workshop role, receipts, the shared parts pool, a bike build and the safety gates, then roll back.

Run from `odoo shell`. This script never commits.
"""

import base64

from odoo.exceptions import AccessError, UserError, ValidationError


def check(label, condition, detail=""):
    if not condition:
        raise SystemExit(f"FAIL {label}: {detail}")
    print("OK", label, detail)


def product(code):
    found = env["product.product"].search([("default_code", "=", code)], limit=1)
    if not found:
        raise SystemExit(f"missing product {code}")
    return found


def on_hand(code):
    env.invalidate_all()
    return product(code).with_context(warehouse_id=WAREHOUSE.id).qty_available


def sellable(code):
    env.invalidate_all()
    return product(code)._hagen_sellable_qty(WAREHOUSE)


def finish(picking_or_mo, method):
    result = getattr(picking_or_mo, method)()
    while isinstance(result, dict) and result.get("res_model"):
        wizard = env[result["res_model"]].with_user(picking_or_mo.env.user).with_context(**(result.get("context") or {}))
        record = wizard.browse(result["res_id"]) if result.get("res_id") else wizard.create({})
        for name in ("action_confirm", "process", "action_backorder", "action_close_mo", "action_set_quantities_to_reservation"):
            if hasattr(record, name):
                result = getattr(record, name)()
                break
        else:
            raise SystemExit(f"unhandled wizard {result['res_model']}")
    return result


def raises(errors, func):
    try:
        with env.cr.savepoint():
            func()
    except errors:
        return True
    return False


def main():
    global WAREHOUSE
    company = env.company
    WAREHOUSE = env["stock.warehouse"].search([("company_id", "=", company.id)], limit=1)
    stock = WAREHOUSE.lot_stock_id
    suppliers = env.ref("stock.stock_location_suppliers")
    employee = env["res.users"].search([("login", "=", "workshop")], limit=1)
    check("workshop login exists", bool(employee) and employee.has_group("hagen_commerce.group_employee"))
    as_employee = env(user=employee)

    # Role: three apps, no costs, no accounting, no purchasing, no settings.
    Menu = as_employee["ir.ui.menu"]
    roots = Menu.browse(Menu._visible_menu_ids()).sudo().filtered(lambda menu: not menu.parent_id)
    wanted = {env.ref(x).id for x in ("sale.sale_menu_root", "stock.menu_stock_root", "mrp.menu_mrp_root")}
    check("employee home shows three apps", set(roots.ids) == wanted, ", ".join(roots.with_context(lang="en_US").mapped("name")))
    form = as_employee["product.template"].get_views([(False, "form"), (False, "list")])
    arch = " ".join(view["arch"] for view in form["views"].values())
    check(
        "cost and vendor prices hidden on products",
        not any(f'name="{name}"' in arch for name in ("standard_price", "seller_ids", "variant_seller_ids")),
    )
    check("supplier price list returns nothing", not as_employee["product.supplierinfo"].search([]))
    bill_vendor = env["res.partner"].create({"name": "Bill test supplier"})
    bill = env["account.move"].create({
        "move_type": "in_invoice",
        "partner_id": bill_vendor.id,
        "invoice_line_ids": [(0, 0, {"name": "Frames", "quantity": 1, "price_unit": 99000})],
    })
    check("vendor bills invisible to the employee", not as_employee["account.move"].search([("id", "=", bill.id)]))
    for model in ("account.payment", "hagen.woo.store", "res.config.settings"):
        check(f"employee blocked from {model}", raises(AccessError, lambda m=model: as_employee[m].search([], limit=1).read(["id"])))
    as_employee["sale.order"].search([], limit=1)
    as_employee["mrp.production"].search([], limit=1)
    as_employee["stock.picking"].search([], limit=1)
    admin_arch = env["product.template"].with_user(env.ref("base.user_admin")).get_views([(False, "form")])["views"]["form"]["arch"]
    check("office still sees cost", 'name="standard_price"' in admin_arch)

    # Safety gate: stock-master shops stay off until the opening count is applied.
    store = env["hagen.woo.store"].with_context(active_test=False).search([("name", "=", "Blurby store")], limit=1)
    check("Blurby store is off", not store.active and store.stock_sync)
    check("cannot switch Blurby store on before the count", raises(ValidationError, lambda: store.write({"active": True})))
    check("stock push blocked before the count", raises(UserError, store._push_stock))
    check("all 22 shops are off", not env["hagen.woo.store"].search_count([]))
    cron = env.ref("hagen_commerce.ir_cron_hagen_woo_sync")
    check("sync runs every 15 minutes", cron.active and cron.interval_number == 15 and cron.interval_type == "minutes")

    before = {code: sellable(code) for code in ("FS-HAGEN-FLAGSHIP", "M-005", "FS-HAGEN-FLAGSHIP-E", "M-006")}
    check("sheet has no Hagen forks, so Hagen kits start at 0", all(v == 0 for v in before.values()), str(before))

    # Receiving without a purchase order: New, add a line, quantity, Validate.
    receipt = as_employee["stock.picking"].create({
        "picking_type_id": WAREHOUSE.in_type_id.id,
        "location_id": suppliers.id,
        "location_dest_id": stock.id,
        "move_ids": [
            (0, 0, {"product_id": product("A65").id, "product_uom_qty": 2, "location_id": suppliers.id, "location_dest_id": stock.id}),
            (0, 0, {"product_id": product("A96").id, "product_uom_qty": 8, "location_id": suppliers.id, "location_dest_id": stock.id}),
        ],
    })
    finish(receipt, "button_validate")
    check("direct receipt validated by the employee", receipt.state == "done", receipt.name)
    check("on hand updated", on_hand("A65") == 2 and on_hand("A96") == 8, f"A65={on_hand('A65')} A96={on_hand('A96')}")
    after = {code: sellable(code) for code in ("FS-HAGEN-FLAGSHIP", "M-005", "FS-HAGEN-FLAGSHIP-E", "FS-HAGEN-XL-E")}
    check("receipt raised frameset and bike counts", after == {"FS-HAGEN-FLAGSHIP": 1, "M-005": 1, "FS-HAGEN-FLAGSHIP-E": 2, "FS-HAGEN-XL-E": 2}, str(after))

    # Receiving against a purchase order, partial delivery, automatic backorder.
    vendor = env["res.partner"].create({"name": "Brose test supplier", "supplier_rank": 1})
    po = env["purchase.order"].create({
        "partner_id": vendor.id,
        "order_line": [(0, 0, {"product_id": product("A78").id, "product_qty": 3, "price_unit": 150000})],
    })
    po.button_confirm()
    po_receipt = as_employee["stock.picking"].browse(po.picking_ids.ids)
    check("PO created a scheduled receipt", len(po_receipt) == 1 and po_receipt.name.startswith("WH/IN/"), po_receipt.name)
    po_receipt.move_ids.quantity = 1
    finish(po_receipt, "button_validate")
    backorder = env["stock.picking"].search([("backorder_id", "=", po_receipt.id)])
    check("partial receipt done", po_receipt.state == "done" and on_hand("A78") == 1)
    check("backorder opened for the rest", len(backorder) == 1 and backorder.move_ids.product_uom_qty == 2, backorder.name)
    picking_views = as_employee["stock.picking"].get_views([(False, "form"), (False, "list")])
    picking_arch = " ".join(view["arch"] for view in picking_views["views"].values())
    check("receipt screen shows no purchase price", 'name="price_unit"' not in picking_arch and "amount_total" not in picking_arch)
    check("Purchase app is not on the employee menu", env.ref("purchase.menu_purchase_root").id not in Menu._visible_menu_ids())
    check("Flagship electric now buildable", sellable("M-006") == 1, str(sellable("M-006")))

    # Shared pool: a frameset sale lowers the bike, a bike sale lowers the frameset.
    customer = env["res.partner"].create({"name": "Pool test customer", "country_id": env.ref("base.hu").id})
    kit_sale = env["sale.order"].create({
        "partner_id": customer.id,
        "order_line": [(0, 0, {"product_id": product("FS-HAGEN-FLAGSHIP").id, "product_uom_qty": 1, "price_unit": 1})],
    })
    kit_sale.action_confirm()
    pool = {code: sellable(code) for code in ("FS-HAGEN-FLAGSHIP", "M-005", "FS-HAGEN-FLAGSHIP-E", "M-006")}
    check("frameset sale lowered the matching bike", pool["FS-HAGEN-FLAGSHIP"] == 0 and pool["M-005"] == 0, str(pool))
    check("frameset sale lowered other Hagen fork users", pool["FS-HAGEN-FLAGSHIP-E"] == 1 and pool["M-006"] == 1, str(pool))
    check("Woo push uses the same number", store._qty_for_store(product("M-005")) == 0)

    bike_sale = env["sale.order"].create({
        "partner_id": customer.id,
        "order_line": [(0, 0, {"product_id": product("M-006").id, "product_uom_qty": 1, "price_unit": 1})],
    })
    bike_sale.action_confirm()
    mo = bike_sale.mrp_production_ids
    check("bike sale opened a manufacturing order", len(mo) == 1 and mo.bom_id.code == "Confirmed recipe", mo.name)
    pool = {code: sellable(code) for code in ("M-006", "FS-HAGEN-FLAGSHIP-E")}
    check("bike sale lowered the frameset", pool == {"M-006": 0, "FS-HAGEN-FLAGSHIP-E": 0}, str(pool))

    # Building the bike as the employee.
    mo_employee = as_employee["mrp.production"].browse(mo.id)
    mo_employee.action_assign()
    finish(mo_employee, "button_mark_done")
    check("employee marked the bike built", mo.state == "done", mo.name)
    check("build used the parts", on_hand("A62") == 5 and on_hand("A78") == 0 and on_hand("A65") == 1, f"A62={on_hand('A62')} A78={on_hand('A78')} A65={on_hand('A65')}")
    delivery = as_employee["stock.picking"].browse(bike_sale.picking_ids.filtered(lambda p: p.picking_type_code == "outgoing").ids)
    delivery.action_assign()
    check("bike delivery is ready", delivery.state == "assigned", delivery.state)
    finish(delivery, "button_validate")
    check("employee shipped the bike", delivery.state == "done" and on_hand("M-006") == 0)

    kit_delivery = as_employee["stock.picking"].browse(kit_sale.picking_ids.ids)
    kit_delivery.action_assign()
    finish(kit_delivery, "button_validate")
    check("frameset shipped as its parts", kit_delivery.state == "done" and on_hand("A61") == 0 and on_hand("A96") == 0,
          f"A61={on_hand('A61')} A96={on_hand('A96')}")

    # Labour line: a confirmed SVC-LABOUR row is a costed line that moves no stock.
    labour_csv = (
        "bike_code,part_code,qty_per_bike,bom_type,status\n"
        "M-007,A63,1,manufacture,confirmed\nM-007,A65,1,manufacture,confirmed\n"
        "M-007,A96,4,manufacture,confirmed\nM-007,A126,1,manufacture,confirmed\n"
        "M-007,SVC-LABOUR,3,manufacture,confirmed\n"
    )
    env["hagen.bom.import"].create({"file": base64.b64encode(labour_csv.encode())}).action_import()
    bom = env["mrp.bom"]._bom_find(product("M-007"))[product("M-007")]
    check("labour row loads onto the recipe", "SVC-LABOUR" in bom.bom_line_ids.product_id.mapped("default_code"))
    labour_mo = env["mrp.production"].create({"product_id": product("M-007").id, "product_qty": 1, "bom_id": bom.id})
    labour_mo.action_confirm()
    check("labour line adds no stock move", "SVC-LABOUR" not in labour_mo.move_raw_ids.product_id.mapped("default_code"))

    # Opening count: Apply All defaults to the Opening Inventory 2026 reference and unlocks the shops.
    quant = env["stock.quant"].with_context(inventory_mode=True).search([
        ("product_id", "=", product("A1").id), ("location_id", "=", stock.id)], limit=1)
    quant.inventory_quantity = 3
    wizard = env["stock.inventory.adjustment.name"].create({"quant_ids": [(6, 0, quant.ids)]})
    check("Apply dialog is pre-filled", wizard.inventory_adjustment_name == "Opening Inventory 2026", wizard.inventory_adjustment_name)
    wizard.action_apply()
    check("count applied", on_hand("A1") == 3)
    check("shops can be switched on after the count", not raises(ValidationError, lambda: store.write({"active": True})))

    print("WORKSHOP FLOW OK")


if "env" not in globals():
    raise SystemExit("check_workshop_flow.py must be run from odoo shell")

try:
    main()
finally:
    env.cr.rollback()
