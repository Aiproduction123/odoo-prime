"""Load data/bom_recipe_template.csv through Manufacturing → Import bike recipes.

Run from `odoo shell`. Commits only when the import succeeds.
"""

import base64

PATH = "/opt/hagen-data/bom_recipe_template.csv"

if "env" not in globals():
    raise SystemExit("import_recipes.py must be run from odoo shell")

with open(PATH, "rb") as handle:
    content = handle.read()
wizard = env["hagen.bom.import"].create({"file": base64.b64encode(content), "filename": "bom_recipe_template.csv"})
result = wizard.action_import()
env.cr.commit()
print("RECIPES", result["params"]["message"])
Bom = env["mrp.bom"].with_context(active_test=False)
for bom in Bom.search([("code", "in", ("Confirmed recipe", "Draft for sign-off"))], order="code, product_tmpl_id"):
    print(
        "BOM",
        bom.product_tmpl_id.default_code,
        bom.type,
        "live" if bom.active else "draft",
        len(bom.bom_line_ids),
        " ".join(f"{line.product_id.default_code}x{line.product_qty:g}" for line in bom.bom_line_ids),
    )
