"""Copy counted quantities from data/opening_inventory_2026.csv onto Inventory → Physical Inventory.

Run from `odoo shell`. Rows with an empty counted_qty are skipped, so a part
that was not counted is never set to zero. Nothing is applied: review the
counts in Odoo, then click Apply All and keep the reference
"Opening Inventory 2026".
"""

import csv

PATH = "/opt/hagen-data/opening_inventory_2026.csv"

if "env" not in globals():
    raise SystemExit("load_opening_counts.py must be run from odoo shell")

warehouse = env["stock.warehouse"].search([("company_id", "=", env.company.id)], limit=1)
location = warehouse.lot_stock_id
Quant = env["stock.quant"].with_context(inventory_mode=True)
loaded, skipped, problems = 0, 0, []
with open(PATH, encoding="utf-8-sig") as handle:
    for row in csv.DictReader(handle):
        raw = (row.get("counted_qty") or "").strip().replace(",", ".")
        if not raw:
            skipped += 1
            continue
        code = row["code"].strip()
        try:
            counted = float(raw)
        except ValueError:
            problems.append(f"{code}: '{raw}' is not a number")
            continue
        if counted < 0:
            problems.append(f"{code}: negative count")
            continue
        product = env["product.product"].search([("default_code", "=", code)], limit=1)
        if not product or not product.is_storable:
            problems.append(f"{code}: no storable product")
            continue
        if env["mrp.bom"]._bom_find(product, bom_type="phantom").get(product):
            problems.append(f"{code}: kit, count its parts instead")
            continue
        quant = Quant.search([("product_id", "=", product.id), ("location_id", "=", location.id)], limit=1)
        if not quant:
            quant = Quant.create({"product_id": product.id, "location_id": location.id})
        quant.inventory_quantity = counted
        loaded += 1

if problems:
    env.cr.rollback()
    raise SystemExit("Nothing loaded. Fix these rows first:\n" + "\n".join(problems))
env.cr.commit()
print(f"COUNTS loaded={loaded} left_blank={skipped}. Review them under Inventory → Physical Inventory, then Apply All.")
