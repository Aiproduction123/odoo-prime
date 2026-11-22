"""Check the blurbybike.com and hagenbikes.com option mapping end to end, then roll back.

Run from `odoo shell`:
    sudo docker compose exec -T odoo odoo shell -d blurby --no-http < scripts/check_webshop_options.py

Covers every Blurby variation, the Hagen drivetrains (Deore 10s, Nexus 5s, Alfine 8s),
handlebars, panels, accessories, framesets with extras and RAL colours, on the order
line, the MO (screen and print), the delivery and the invoice. Nothing is committed.
"""
from itertools import product as combinations

from odoo.addons.hagen_commerce.models import webshop_options as options
from odoo.addons.hagen_commerce.models.woo_store import OPENING_DONE_PARAM

if "env" not in globals():
    raise SystemExit("check_webshop_options.py must be run from odoo shell")

failures = []
counts = {}


def expect(condition, message):
    if not condition:
        failures.append(message)


def tally(name):
    counts[name] = counts.get(name, 0) + 1


# --- blurbybike.com: the five variable products exactly as the shop lists them ---------------
SIZES_LMS = ["L (181 - 205 cm)", "M (160 - 180 cm)", "ST (140 - 180 cm)"]
CARBON = ["Alu: Fork, Handlebar, Seatpost", "Carbon: Fork, Handlebar, Seatpost"]
RACK = ["With", "Without"]
BLURBY = {
    "Blurby Trekking Ebike": ("M-001", {"Size": SIZES_LMS, "Colour": ["Matte Black", "Metallic copper"], "Luggage rack": RACK}),
    "Blurby Gravel Ebike": ("M-003", {
        "Size": SIZES_LMS[:2], "Colour": ["Matte Black", "Metallic Green"],
        "Pedals": ["Blurby Flat Pedals", "Shimano SPD Pedals"], "Carbon package": CARBON,
    }),
    "Blurby W Ebike": ("M-004", {
        "Size": ["M (160 - 180 cm)", "S (140 - 160 cm)"], "Colour": ["Cherry Red", "Light blue", "Matte Black"],
        "Carbon package": CARBON, "Luggage rack": RACK,
    }),
    "Blurby Max Ebike": ("M-002", {
        "Size": SIZES_LMS, "Colour": ["Anthracite", "Matte Black", "Moon Grey", "Navy Blue"],
        "Carbon package": CARBON, "Luggage rack": RACK,
    }),
    "Blurby Bike Ebike": ("M-004", {"Size": SIZES_LMS, "Colour": ["Custom color", "Matte Black"], "Carbon package": CARBON, "Luggage rack": RACK}),
}
BLURBY_FRAME = {"L": ("A50", "A41"), "M": ("A51", "A40"), "W": ("A52", "A39")}
COLOUR_RAL = {
    "Matte Black": None, "Metallic copper": "RAL 8029", "Metallic Green": "RAL 6036", "Cherry Red": "RAL 3032",
    "Light blue": None, "Anthracite": None, "Moon Grey": "RAL 9022", "Navy Blue": "RAL 5026",
    "Custom color": "RAL: see customer note",
}


def blurby_expected(name, chosen):
    size_text = chosen["Size"]
    if name == "Blurby W Ebike" or size_text.startswith(("ST", "S ")):
        size = "W"
    else:
        size = size_text[0]
    replace = []
    if size != "L":
        frame, guard = BLURBY_FRAME[size]
        replace += [["A50", frame], ["A41", guard]]
    if chosen.get("Carbon package", "").startswith("Carbon"):
        replace += [["A55", "A57"], ["A29", "A30"]]
    return size, sorted(replace)


for name, (code, attributes) in BLURBY.items():
    labels = list(attributes)
    for values in combinations(*attributes.values()):
        chosen = dict(zip(labels, values))
        size, replace = blurby_expected(name, chosen)
        variation = {"sku": "", "status": "publish", "attributes": [{"name": k, "option": v} for k, v in chosen.items()]}
        line = {"name": f"{name} - " + ", ".join(values), "sku": "", "meta_data": [
            {"key": f"pa_{k.lower().replace(' ', '-')}", "display_key": k, "display_value": v} for k, v in chosen.items()
        ]}
        for shape, build in (("variation", options.resolve_variation(name, variation)), ("order line", options.resolve_line(line))):
            where = f"{name} {chosen} ({shape})"
            expect(build["code"] == code, f"{where}: code {build['code']}, expected {code}")
            expect(sorted(build["replace"]) == replace, f"{where}: swaps {sorted(build['replace'])}, expected {replace}")
            expect(not build["remove"] and not build["add"], f"{where}: unexpected remove/add")
            notes = "\n".join(build["notes"])
            expect(f"Frame colour: {chosen['Colour']}" in notes, f"{where}: colour missing from notes")
            ral = COLOUR_RAL[chosen["Colour"]]
            expect((ral in notes) if ral else ("RAL not on the Paints tab" in notes), f"{where}: RAL note wrong: {notes}")
            expect("Website options:" in notes, f"{where}: option summary missing")
            warnings = "\n".join(build["warnings"])
            expect(("luggage rack" in warnings) == (chosen.get("Luggage rack") == "With"), f"{where}: rack warning wrong")
            expect(("Pedals" in warnings) == ("Pedals" in chosen), f"{where}: pedal warning wrong")
            tally(f"blurby {shape}")
expect(counts.get("blurby variation") == 124, f"expected 124 Blurby variations, checked {counts.get('blurby variation')}")


# --- hagenbikes.com configurator -----------------------------------------------------------------
def hagen_line(model, *pairs, blob=False, sku=""):
    if blob:
        text = "<br>".join(f"{label}: {value}" for label, value in pairs)
        meta = [{"key": "Configuration", "display_key": "Configuration", "display_value": text}]
    else:
        meta = [{"key": f"option_{i}", "display_key": label, "display_value": value} for i, (label, value) in enumerate(pairs)]
    return {"name": model, "sku": sku, "meta_data": meta}


NON_ELECTRIC = "Non-electric"
BROSE = "90 Nm Brose Mid-Motor (+ 3100.00 €)"
FRAME_SET = "Frame set"
GEARS = {
    "deore": ("External 10s chain - Shimano Deore", [], []),
    "nexus": ("Internal 5s - Shimano Nexus (+ 290.00 €)", [["A154", "A157"], ["A156", "A158"]], ["A8"]),
    "alfine": ("Internal 8s belt - Shimano Alfine (+ 700.00 €)", [["A154", "A159"], ["A156", "A160"]], ["A8"]),
}
for model, model_key in (("Hagen FLAGSHIP", "FLAGSHIP"), ("Hagen XL", "XL")):
    for type_value, electric in ((NON_ELECTRIC, False), (BROSE, True)):
        for gear, (gear_value, replace, remove) in GEARS.items():
            for blob in (False, True):
                build = options.resolve_line(hagen_line(
                    model, ("01 Colors", "Black"), ("02 Type", type_value), ("03 Gearing and Drivetrain", gear_value),
                    ("04 Handlebar", "Riser"), blob=blob,
                ))
                where = f"{model} {type_value} {gear} blob={blob}"
                code = options.HAGEN_BIKES[(model_key, electric)]
                expect(build["code"] == code, f"{where}: code {build['code']}, expected {code}")
                expect(sorted(build["replace"]) == sorted(replace), f"{where}: swaps {build['replace']}")
                expect(build["remove"] == remove, f"{where}: removed {build['remove']}")
                expect(any("RAL 9005" in note for note in build["notes"]), f"{where}: RAL 9005 missing")
                alfine_warning = any("non-electric bikes only" in warning for warning in build["warnings"])
                expect(alfine_warning == (gear == "alfine" and electric), f"{where}: Alfine/electric warning wrong")
                tally("hagen drivetrain")

for handlebar, swap in (("Flat", [["A98", "A99"]]), ("Riser", []), ("Cruiser", [["A98", "A28"]])):
    build = options.resolve_line(hagen_line("Hagen FLAGSHIP", ("02 Type", NON_ELECTRIC), ("04 Handlebar", handlebar)))
    expect(build["replace"] == swap, f"handlebar {handlebar}: {build['replace']}")
    tally("hagen handlebar")

for model, grey_swaps in (("Hagen FLAGSHIP", [["A110", "A112"], ["A111", "A113"], ["A102", "A103"]]), ("Hagen XL", [["A104", "A105"]])):
    build = options.resolve_line(hagen_line(model, ("02 Type", NON_ELECTRIC), ("06 Panels", "Grey")))
    for pair in grey_swaps:
        expect(pair in build["replace"], f"{model} grey panels: {pair} missing from {build['replace']}")
    tally("hagen panels")

ACCESSORIES = (
    ("Wide Box (+ 349.00 €)", [["A115", 1.0]]),
    ("Child seat (+ 199.00 €)", [["A124", 1.0]]),
    ("Front child seat", [["A125", 1.0]]),
    ("Canopy", [["A151", 2.0]]),
    ("Rack adapter", [["A130", 1.0]]),
    ("Ergotec 3 Up and Down Adapter (+ 99.00 €)", [["A118", 1.0]]),
)
for value, parts in ACCESSORIES:
    build = options.resolve_line(hagen_line("Hagen XL", ("02 Type", BROSE), ("05 Accessories", value)))
    expect([row[:2] for row in build["add"]] == parts, f"accessory {value}: {build['add']}")
    tally("hagen accessory")
build = options.resolve_line(hagen_line("Hagen XL", ("02 Type", NON_ELECTRIC), ("05 Accessories", "Side Panels (+ 299.00 €)")))
expect(not build["add"] and any("XL side panels" in w for w in build["warnings"]), "XL side panels must warn, not deduct")

# German labels and RAL colours
build = options.resolve_line(hagen_line("Hagen FLAGSHIP", ("01 Farben", "Gelb"), ("02 Typ", "Nicht-elektrisch")))
expect(build["code"] == "M-005" and any("RAL 1023" in n for n in build["notes"]), f"German labels: {build}")
for colour, ral in (("Black", "RAL 9005"), ("White", "RAL 9003"), ("Yellow", "RAL 1023"), ("Matt black", None)):
    build = options.resolve_line(hagen_line("Hagen XL", ("01 Colors", colour), ("02 Type", NON_ELECTRIC)))
    note = next(n for n in build["notes"] if n.startswith("Frame colour"))
    expect((ral in note) if ral else ("RAL" not in note), f"{colour}: {note}")
    tally("ral colour")
build = options.resolve(
    "Hagen XL", [("01 Colors", "Custom (+ 250.00 €)"), ("02 Type", NON_ELECTRIC)],
    note="My Custom RAL for the Bike would be RAL 570-M",
)
expect(any("RAL 570-M (customer note)" in n for n in build["notes"]), f"custom RAL: {build['notes']}")
expect(any(n.startswith("Customer note:") for n in build["notes"]), "custom colour must carry the customer note")
tally("ral colour")

# Framesets: non-electric only, extras listed for the order
build = options.resolve_line(hagen_line("Hagen XL", ("02 Type", "Frame set electric")))
expect(build["code"] == "FS-HAGEN-XL", f"electric frame set must map to the non-electric kit: {build['code']}")
build = options.resolve_line(hagen_line(
    "Hagen FLAGSHIP", ("02 Type", FRAME_SET), ("06 Panels", "Grey"),
    ("05 Accessories", "Side Panels"), ("05 Accessories", "Floor plate"), ("05 Accessories", "Wide Box"),
    ("05 Accessories", "Front child seat"), ("05 Accessories", "Canopy"), ("05 Accessories", "Rack adapter"),
))
expect(build["code"] == "FS-HAGEN-FLAGSHIP", f"frameset code {build['code']}")
expect(sorted(row[0] for row in build["add"]) == ["A103", "A112", "A113", "A115", "A125", "A130", "A151"], f"frameset extras {build['add']}")
expect(not build["replace"] and not build["remove"], "frameset must not swap parts")
expect(options.resolve_line(hagen_line("Hagen MINI", ("02 Type", FRAME_SET)))["code"] is None, "Hagen Mini is discontinued")
expect(options.resolve("Wide Box", [], sku="E00302")["code"] == "A115", "Wide Box SKU E00302 -> A115")
tally("frameset")


# --- Odoo end to end -----------------------------------------------------------------------------
company = env.company
warehouse = env["stock.warehouse"].search([("company_id", "=", company.id)], limit=1)
stock_location = warehouse.lot_stock_id
Product = env["product.product"]
Quant = env["stock.quant"]


def part(code):
    found = Product.search([("default_code", "=", code)], limit=1)
    if not found:
        raise SystemExit(f"product {code} is missing")
    return found


def set_free(code, qty):
    product = part(code)
    delta = qty - product._hagen_free_units(warehouse)
    if delta > 0:
        Quant._update_available_quantity(product, stock_location, delta)
    elif delta < 0:
        Quant._update_available_quantity(product, stock_location, delta)
    product.invalidate_recordset()


stores = env["hagen.woo.store"].with_context(active_test=False).search([])
blurby_store = stores.filtered(lambda row: row.name == "Blurby store")[:1]
hagen_store = stores.filtered(lambda row: row.name == "Hagen store")[:1]
if not blurby_store or not hagen_store:
    raise SystemExit("Blurby store or Hagen store is missing")

try:
    # 1. Stock push: every enabled variation gets its own sellable quantity.
    env["ir.config_parameter"].sudo().set_param(OPENING_DONE_PARAM, "1")
    max_bom = Product._hagen_find_bom(part("M-002"))
    for line in max_bom.bom_line_ids.filtered(lambda line: line.product_id.is_storable):
        set_free(line.product_id.default_code, 5 * line.product_qty)
    for code, qty in (("A51", 3), ("A40", 5), ("A52", 5), ("A39", 5), ("A57", 1), ("A30", 4)):
        set_free(code, qty)
    finished = int(part("M-002")._hagen_free_units(warehouse))
    variations = [
        (1, "L (181 - 205 cm)", CARBON[0], "publish", 5 + finished),
        (2, "M (160 - 180 cm)", CARBON[0], "publish", 3),
        (3, "M (160 - 180 cm)", CARBON[1], "publish", 1),
        (4, "ST (140 - 180 cm)", CARBON[1], "publish", 1),
        (5, "ST (140 - 180 cm)", CARBON[0], "private", None),
    ]
    sent = {}

    def fake_request(self, method, path, params=None, payload=None):
        if method == "GET" and path == "products":
            if (params or {}).get("page", 1) > 1:
                return []
            return [
                {"id": 8207, "name": "Blurby Max Ebike", "type": "variable", "sku": ""},
                {"id": 7001, "name": "Hagen XL frameset", "type": "simple", "sku": "FS-HAGEN-XL"},
                {"id": 7002, "name": "Wide Box", "type": "simple", "sku": "E00302"},
            ]
        if method == "GET" and path == "products/8207/variations":
            return [{
                "id": vid, "sku": "", "status": status, "attributes": [
                    {"name": "Size", "option": size}, {"name": "Colour", "option": "Navy Blue"},
                    {"name": "Carbon package", "option": carbon}, {"name": "Luggage rack", "option": "Without"},
                ],
            } for vid, size, carbon, status, _qty in variations]
        if method == "POST":
            sent[path] = sent.get(path, []) + payload["update"]
            return {}
        raise AssertionError(f"unexpected request {method} {path}")

    Store = type(blurby_store)
    original = Store._woo_request
    Store._woo_request = fake_request
    try:
        pushed = blurby_store._push_stock()
    finally:
        Store._woo_request = original
    got = {row["id"]: row["stock_quantity"] for row in sent.get("products/8207/variations/batch", [])}
    want = {vid: qty for vid, _size, _carbon, status, qty in variations if status == "publish"}
    expect(got == want, f"variation stock push {got}, expected {want}")
    simple = {row["id"]: row["stock_quantity"] for row in sent.get("products/batch", [])}
    expect(set(simple) == {7001, 7002}, f"simple products pushed: {simple}")
    expect(simple.get(7002) == part("A115")._hagen_sellable_qty(warehouse), "Wide Box SKU alias pushes A115 stock")
    expect(pushed == 6, f"push counted {pushed} rows, expected 6")
    tally("stock push")

    # Seed every recipe and option part so orders can reserve.
    seed = set()
    for bom in env["mrp.bom"].search([("code", "=", "Confirmed recipe")]):
        seed |= set(bom.bom_line_ids.filtered(lambda line: line.product_id.is_storable).product_id.mapped("default_code"))
    seed |= {"A51", "A52", "A39", "A40", "A57", "A30", "A157", "A158", "A159", "A160", "A99", "A28", "A112", "A113",
             "A103", "A105", "A115", "A124", "A125", "A151", "A130", "A118"}
    for code in seed:
        set_free(code, 50)

    def order(store, number, items, note=""):
        return store._import_paid_order({
            "id": 990000 + number, "number": str(990000 + number), "status": "processing",
            "date_paid": "2026-11-22T12:00:00", "payment_method": "stripe", "payment_method_title": "Stripe",
            "currency": "HUF", "customer_note": note,
            "billing": {"first_name": "Option", "last_name": f"Test {number}", "email": f"options-{number}@example.com",
                        "address_1": "Teszt utca 1.", "city": "Budapest", "postcode": "1211", "country": "HU"},
            "line_items": [{**item, "quantity": item.get("quantity", 1), "total": item.get("total", "1000.00")} for item in items],
        })

    def mo_for(sale_line):
        return env["mrp.production"].search([("sale_line_id", "=", sale_line.id)])

    def raw_codes(production):
        return set(production.move_raw_ids.filtered(lambda move: move.state != "cancel").product_id.mapped("default_code"))

    def invoice_text(sale):
        return "\n".join(sale.invoice_ids.invoice_line_ids.mapped("name"))

    # 2. Hagen XL electric, Alfine, Widebox + rear child seat, custom RAL in the customer note.
    sale = order(hagen_store, 1, [hagen_line(
        "Hagen XL", ("01 Colors", "Custom (+ 250.00 €)"), ("02 Type", BROSE),
        ("03 Gearing and Drivetrain", GEARS["alfine"][0]), ("04 Handlebar", "Riser"),
        ("05 Accessories", "Wide Box"), ("05 Accessories", "Child seat"), blob=True,
    )], note="My Custom RAL for the Bike would be RAL 570-M")
    line = sale.order_line.filtered(lambda row: row.product_id.default_code == "M-008")
    production = mo_for(line)
    expect(len(production) == 1, f"M-008 order made {len(production)} MOs")
    codes = raw_codes(production)
    expect({"A159", "A160", "A115", "A124", "A64", "A78"} <= codes, f"M-008 MO parts missing: {codes}")
    expect(not {"A154", "A156", "A8"} & codes, f"M-008 MO kept base drivetrain: {codes & {'A154', 'A156', 'A8'}}")
    expect("RAL 570-M" in (production.hagen_build_notes or ""), "MO notes lack the custom RAL")
    expect("Shimano Alfine 8-speed" in (production.hagen_build_notes or ""), "MO notes lack the drivetrain")
    expect("RAL 570-M" in invoice_text(sale) and "Website options:" in invoice_text(sale), "invoice lacks RAL/options")
    html = env["ir.actions.report"]._render_qweb_html("mrp.report_mrporder", production.ids)[0].decode()
    expect("RAL 570-M" in html and "Webshop build options" in html, "printed MO lacks the build options")
    tally("order hagen alfine")

    # 3. Hagen Flagship non-electric, Nexus, flat bar, grey panels; two lines must not merge into one MO.
    flagship = hagen_line(
        "Hagen FLAGSHIP", ("01 Colors", "White"), ("02 Type", NON_ELECTRIC), ("03 Gearing and Drivetrain", GEARS["nexus"][0]),
        ("04 Handlebar", "Flat"), ("06 Panels", "Grey"),
    )
    deore = hagen_line("Hagen FLAGSHIP", ("01 Colors", "Yellow"), ("02 Type", NON_ELECTRIC), ("03 Gearing and Drivetrain", GEARS["deore"][0]))
    sale = order(hagen_store, 2, [flagship, deore])
    nexus_line, deore_line = sale.order_line.filtered(lambda row: row.product_id.default_code == "M-005")
    nexus_mo, deore_mo = mo_for(nexus_line), mo_for(deore_line)
    expect(len(nexus_mo) == 1 and len(deore_mo) == 1 and nexus_mo != deore_mo, "configured lines must get their own MOs")
    codes = raw_codes(nexus_mo)
    expect({"A157", "A158", "A99", "A112", "A113", "A103", "A61"} <= codes, f"Nexus MO parts missing: {codes}")
    expect(not {"A154", "A156", "A8", "A98", "A110", "A111", "A102"} & codes, f"Nexus MO kept base parts: {codes}")
    codes = raw_codes(deore_mo)
    expect({"A154", "A156", "A8", "A98", "A110", "A102"} <= codes, f"Deore MO is not the base recipe: {codes}")
    expect("RAL 9003" in invoice_text(sale) and "RAL 1023" in invoice_text(sale), "invoice lacks RAL 9003/1023")
    tally("order hagen nexus/deore")

    # 4. Flagship frameset with extras: extras become order lines and leave with the delivery.
    sale = order(hagen_store, 3, [hagen_line(
        "Hagen FLAGSHIP", ("01 Colors", "Black"), ("02 Type", FRAME_SET), ("06 Panels", "Grey"),
        ("05 Accessories", "Side Panels"), ("05 Accessories", "Floor plate"), ("05 Accessories", "Wide Box"),
        ("05 Accessories", "Front child seat"), ("05 Accessories", "Canopy"), ("05 Accessories", "Rack adapter"),
    )])
    lines = {row.product_id.default_code: row for row in sale.order_line}
    expect({"FS-HAGEN-FLAGSHIP", "A112", "A113", "A103", "A115", "A125", "A151", "A130"} <= set(lines), f"frameset SO lines {sorted(lines)}")
    expect(all(lines[code].price_unit == 0 for code in ("A115", "A125", "A151", "A130")), "extras must be included at price 0")
    expect(lines.get("A151") and lines["A151"].product_uom_qty == 2, "canopy needs 2 clamps")
    picking = sale.picking_ids.filtered(lambda p: p.picking_type_code == "outgoing")[:1]
    moved = set(picking.move_ids.product_id.mapped("default_code"))
    expect({"A61", "A65", "A96", "A131", "A128", "A161", "A115", "A125", "A151", "A130", "A112", "A113", "A103"} <= moved,
           f"frameset delivery moves {sorted(moved)}")
    before = {code: part(code).qty_available for code in ("A61", "A115")}
    for move in picking.move_ids:
        move.quantity = move.product_uom_qty
        move.picked = True
    picking.with_context(skip_backorder=True, cancel_backorder=True).button_validate()
    expect(picking.state == "done", f"frameset delivery state {picking.state}")
    for code in ("A61", "A115"):
        product = part(code)
        product.invalidate_recordset()
        expect(abs(product.qty_available - (before[code] - 1)) < 1e-6,
               f"{code}: delivery left {product.qty_available}, expected {before[code] - 1}")
    tally("order frameset extras")

    # 5. Blurby Gravel M carbon (no mudguards) and Blurby W S with rack, as WooCommerce order lines.
    gravel = {"name": "Blurby Gravel Ebike - M (160 - 180 cm), Matte Black", "sku": "", "meta_data": [
        {"key": "pa_bike-frame", "display_key": "Size", "display_value": "M (160 - 180 cm)"},
        {"key": "pa_colour", "display_key": "Colour", "display_value": "Matte Black"},
        {"key": "pa_pedals", "display_key": "Pedals", "display_value": "Shimano SPD Pedals"},
        {"key": "pa_carbon-pack", "display_key": "Carbon package", "display_value": CARBON[1]},
    ]}
    w_bike = {"name": "Blurby W Ebike - S (140 - 160 cm), Cherry Red", "sku": "1-1", "meta_data": [
        {"key": "pa_bike-frame", "display_key": "Size", "display_value": "S (140 - 160 cm)"},
        {"key": "pa_colour", "display_key": "Colour", "display_value": "Cherry Red"},
        {"key": "pa_carbon-pack", "display_key": "Carbon package", "display_value": CARBON[0]},
        {"key": "pa_luggage-rack", "display_key": "Luggage rack", "display_value": "With"},
    ]}
    sale = order(blurby_store, 4, [gravel, w_bike])
    gravel_line = sale.order_line.filtered(lambda row: row.product_id.default_code == "M-003")
    w_line = sale.order_line.filtered(lambda row: row.product_id.default_code == "M-004")
    codes = raw_codes(mo_for(gravel_line))
    expect({"A51", "A57", "A30"} <= codes and not {"A50", "A55", "A29", "A40", "A41"} & codes, f"Gravel M carbon MO {sorted(codes)}")
    expect("CHECK:" not in (mo_for(gravel_line).hagen_build_notes or "").split("Pedals")[0], "Gravel must not warn about mudguards")
    codes = raw_codes(mo_for(w_line))
    expect({"A52", "A39", "A55", "A29"} <= codes and not {"A50", "A41"} & codes, f"Blurby W MO {sorted(codes)}")
    expect("CHECK: Blurby luggage rack" in w_line.name and "RAL 3032" in w_line.name, f"Blurby W line text: {w_line.name}")
    expect("RAL 3032" in invoice_text(sale), "Blurby invoice lacks the colour RAL")
    tally("order blurby")
finally:
    env.cr.rollback()

if failures:
    print("WEBSHOP OPTIONS FAILED", len(failures))
    for failure in failures[:40]:
        print("  -", failure)
    raise SystemExit(1)
print("WEBSHOP OPTIONS OK", ", ".join(f"{name}={count}" for name, count in sorted(counts.items())))
