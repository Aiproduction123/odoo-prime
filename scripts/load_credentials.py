"""Copy WooCommerce credentials from the environment into the blurby database.

Run from `odoo shell` (scripts/credentials.sh does that). Stores stay inactive
until Opening Inventory 2026 is applied, so a sync cannot start on an empty count.
Placeholder values such as "change-me" are ignored. Secrets are not printed.
"""

import os

PLACEHOLDERS = {"", "change-me", "changeme"}
MASTERS = (
    ("Blurby store", "https://blurbybike.com", "BLURBY_WC_KEY", "BLURBY_WC_SECRET"),
    ("Blurby HU store", "https://blurbybike.hu", "BLURBY_HU_WC_KEY", "BLURBY_HU_WC_SECRET"),
    ("Hagen store", "https://hagenbikes.com", "HAGEN_WC_KEY", "HAGEN_WC_SECRET"),
)


def env_value(name):
    value = (os.environ.get(name) or "").strip()
    if value.lower() in PLACEHOLDERS:
        return ""
    return value


def commit():
    env.cr.commit()


if "env" not in globals():
    raise SystemExit("load_credentials.py must be run from odoo shell")

company = env.company
Store = env["hagen.woo.store"].with_context(active_test=False)
Network = env["hagen.woo.network"]
journal = env["account.journal"].search([
    ("code", "=", "STRP"),
    ("company_id", "=", company.id),
], limit=1)
opening_done = bool(Store._opening_inventory_applied())

for name, url, key_name, secret_name in MASTERS:
    store = Store.search([("name", "=", name), ("company_id", "=", company.id)], limit=1)
    values = {"base_url": url, "stock_sync": True}
    if not opening_done:
        values["active"] = False
    key = env_value(key_name)
    secret = env_value(secret_name)
    if key:
        values["consumer_key"] = key
    if secret:
        values["consumer_secret"] = secret
    if store:
        if opening_done:
            values.pop("stock_sync", None)
        store.write(values)
    else:
        values.update({
            "name": name,
            "company_id": company.id,
            "payment_journal_id": journal.id,
            "active": False,
            "stock_sync": True,
        })
        store = Store.create(values)
    print(
        "STORE",
        store.name,
        "active=" + str(bool(store.active)),
        "stock_sync=" + str(bool(store.stock_sync)),
        "key=" + ("set" if store.consumer_key else "empty"),
        "secret=" + ("set" if store.consumer_secret else "empty"),
    )

network = Network.search([
    ("name", "=", "Rattaproff network"),
    ("company_id", "=", company.id),
], limit=1)
if not network:
    network = Network.create({
        "name": "Rattaproff network",
        "root_url": "https://rattaproff.ee",
        "company_id": company.id,
    })
network_values = {}
wp_user = env_value("RATTAPROFF_WP_USER")
app_password = env_value("RATTAPROFF_APP_PASSWORD")
if wp_user:
    network_values["wp_username"] = wp_user
if app_password:
    network_values["application_password"] = app_password
if network_values:
    network.write(network_values)
if not opening_done:
    Store.search([("company_id", "=", company.id)]).write({"active": False})

print(
    "NETWORK",
    network.name,
    "user=" + ("set" if network.wp_username else "empty"),
    "app_password=" + ("set" if network.application_password else "empty"),
    "shops=" + str(len(network.store_ids)),
)
active = Store.search_count([("company_id", "=", company.id), ("active", "=", True)])
print("ACTIVE_STORES", active, "opening_inventory=" + ("applied" if opening_done else "waiting"))
commit()
