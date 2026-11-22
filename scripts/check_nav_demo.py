# Run with:
#   ./scripts/fetch_nav_xsd.sh   (once, optional: enables schema validation)
#   sudo docker compose exec -T odoo odoo shell -d blurby --no-http < scripts/check_nav_demo.py
#
# Posts two test invoices, builds their NAV 3.0 XML, validates it against the
# official schema and runs the NAV upload in Demo mode. Everything is rolled
# back, nothing reaches NAV and no invoice number is kept.
import os

from lxml import etree

from odoo import Command, fields
from odoo.addons.l10n_hu_edi.models.l10n_hu_edi_connection import L10nHuEdiConnection

XSD_DIR = "/opt/hagen-data/nav_xsd"


def schema():
    if not os.path.exists(os.path.join(XSD_DIR, "invoiceData.xsd")):
        return None
    locations = {
        "http://schemas.nav.gov.hu/NTCA/1.0/common": "common.xsd",
        "http://schemas.nav.gov.hu/OSA/3.0/base": "invoiceBase.xsd",
    }

    class Resolver(etree.Resolver):
        def resolve(self, url, pubid, context):
            name = os.path.basename(url)
            return self.resolve_filename(os.path.join(XSD_DIR, name), context)

    def load(name):
        tree = etree.parse(os.path.join(XSD_DIR, name))
        for node in tree.getroot().iter("{http://www.w3.org/2001/XMLSchema}import"):
            node.set("schemaLocation", locations[node.get("namespace")])
        return tree

    parser = etree.XMLParser()
    parser.resolvers.add(Resolver())
    tree = load("invoiceData.xsd")
    for name in ("invoiceBase.xsd", "common.xsd"):
        load(name).write(f"/tmp/{name}")
    tree.write("/tmp/invoiceData.xsd")
    return etree.XMLSchema(etree.parse("/tmp/invoiceData.xsd"))


def text(root, path):
    found = root.xpath(path)
    return found[0].text if found else None


company = env.company
if company.l10n_hu_edi_server_mode != "demo":
    raise SystemExit(f"NAV mode is {company.l10n_hu_edi_server_mode}, expected demo")

xsd = schema()
huf = env.ref("base.HUF")
eur = env.ref("base.EUR")
tax = env["account.chart.template"].with_company(company).ref("F27")
product = env["product.product"].search([("default_code", "=", "M-005")], limit=1)
partners = {
    "b2b": env["res.partner"].create({
        "name": "NAV Demo Kft.", "is_company": True, "vat": "27725414-2-13",
        "country_id": env.ref("base.hu").id, "zip": "1211", "city": "Budapest", "street": "Teszt utca 1.",
    }),
    "b2c": env["res.partner"].create({
        "name": "Demo Kunde", "country_id": env.ref("base.de").id,
        "zip": "10115", "city": "Berlin", "street": "Teststrasse 1",
    }),
}
results = []
for kind, currency, price in (("b2b", huf, 1_500_000), ("b2c", eur, 2390)):
    move = env["account.move"].create({
        "move_type": "out_invoice",
        "partner_id": partners[kind].id,
        "currency_id": currency.id,
        "invoice_date": fields.Date.today(),
        "invoice_line_ids": [Command.create({
            "product_id": product.id, "quantity": 1, "price_unit": price, "tax_ids": [Command.set(tax.ids)],
        })],
    })
    move.action_post()
    errors = move._l10n_hu_edi_check_invoices()
    if errors:
        raise SystemExit(f"{kind}: NAV pre-checks failed: {[e['message'] for e in errors.values()]}")
    xml = move._l10n_hu_edi_generate_xml()
    root = etree.fromstring(xml)
    if xsd is not None and not xsd.validate(root):
        raise SystemExit(f"{kind}: XML does not match the NAV 3.0 schema: {xsd.error_log}")
    supplier = "//*[local-name()='supplierTaxNumber']/*[local-name()='%s']"
    tax_number = "-".join(text(root, supplier % part) or "?" for part in ("taxpayerId", "vatCode", "countyCode"))
    with L10nHuEdiConnection(env) as connection:
        move._l10n_hu_edi_upload(connection)
        move._l10n_hu_edi_query_status(connection)
    if move.l10n_hu_edi_state not in ("confirmed", "confirmed_warning"):
        raise SystemExit(f"{kind}: demo upload ended in {move.l10n_hu_edi_state}: {move.l10n_hu_edi_messages}")
    results.append(
        f"{kind} {currency.name} supplier={tax_number} "
        f"seat={text(root, '//*[local-name()=\"supplierAddress\"]//*[local-name()=\"postalCode\"]')} "
        f"vat={text(root, '//*[local-name()=\"invoiceVatAmountHUF\"]')} HUF "
        f"rate={text(root, '//*[local-name()=\"exchangeRate\"]')} demo={move.l10n_hu_edi_state}"
    )

env.cr.rollback()

# The guard: NAV cannot leave Demo until all four technical-user credentials are entered.
from odoo.exceptions import UserError, ValidationError

blocked = []
try:
    with env.cr.savepoint():
        env.company.l10n_hu_edi_server_mode = "production"
        env.company.flush_recordset()
except ValidationError:
    blocked.append("settings")
wizard = env["hagen.nav.golive"].create({"mode": "test"})
if wizard.tax_number != "25979923-2-43" or not wizard.extract_confirmed:
    raise SystemExit(f"NAV wizard defaults are {wizard.tax_number} / {wizard.extract_confirmed}")
try:
    with env.cr.savepoint():
        wizard.action_switch()
except UserError:
    blocked.append("missing credentials")
wizard.write({
    "l10n_hu_edi_username": "fake-user", "l10n_hu_edi_password": "fake",
    "l10n_hu_edi_signature_key": "fake-signature-key", "l10n_hu_edi_replacement_key": "fake-replacement-key",
})
try:
    with env.cr.savepoint():
        wizard.action_switch()
except UserError:
    blocked.append("wrong credentials")
env.cr.rollback()
env.invalidate_all()
if blocked != ["settings", "missing credentials", "wrong credentials"] or env.company.l10n_hu_edi_server_mode != "demo":
    raise SystemExit(f"NAV guard failed: blocked={blocked} mode={env.company.l10n_hu_edi_server_mode}")
results.append("guard blocks: " + ", ".join(blocked))

print("NAV DEMO OK", "schema=checked" if xsd is not None else "schema=skipped (run scripts/fetch_nav_xsd.sh)")
for line in results:
    print(" ", line)
print("  mode stays:", env.company.l10n_hu_edi_server_mode)
