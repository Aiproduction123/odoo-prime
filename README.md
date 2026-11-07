# Hagen Group invoicing

Self-hosted [Odoo 19 Community](https://www.odoo.com/) for **Hagen Group Kft.** (formerly BLURBY Korlátolt Felelősségű Társaság). It covers Hungarian invoicing, the parts catalog, kit recipes for bikes, and a multi-store WooCommerce connector that treats Odoo as the stock master.

Odoo here is the Community edition. The Invoicing app, the Hungarian chart of accounts (27% / 18% / 5% ÁFA), Manufacturing, and the NAV 3.0 e-invoicing module are all in Community. NAV itself is not connected: the company stays in **demo** mode, which mocks the tax authority and does not file anything. Do not switch that mode until the tax number and seat below have been checked against the current company extract.

## What is already filled in

| | |
| --- | --- |
| Legal name | Hagen Group Kft. |
| Seat on invoices | 1053 Budapest, Kecskeméti utca 5. |
| Workshop | 1211 Budapest, Öntő utca 5. (delivery address on the company) |
| Company register | 01-09-299788 |
| Tax number kept on the company | 25979923-2-41 |
| Currency | HUF |
| Email on documents | info@blurbybike.com |
| Sign-in | Ivari Kull, `ivari@blurbybike.com`. Screens are in English. Hungarian is installed; switch it under the user menu → Preferences. |
| Stripe journal | Bank journal **Stripe Payments**, code `STRP` |

Installed apps: **Invoicing**, **Sales**, **Inventory**, **Manufacturing**, plus the **Hagen Group commerce** module. Parts A1–A153 and bike models M-001–M-008 are storable products. Workshop labour stays a service. Sales prices are empty on purpose. The sample draft invoice and the “Sample customer (delete me)” contact are removed.

A court-approved rename to Hagen Group Kft. is already reflected here. Later dealership drafts use tax number `25979923-2-43` and put the seat at Öntő utca 5. as well as the workshop. This database still uses `25979923-2-41` and Kecskeméti utca 5., because those were the figures to keep. Confirm the live company extract before leaving NAV demo mode. No bank account is stored in this setup.

Not loaded: historical invoices, bank accounts, NAV technical-user keys, WooCommerce API keys, or live bike recipes. The inventory sheet’s component lists disagree with the part catalog (codes point at different parts than the row names), so no Bill of Materials is active yet.

## Run it

Docker and Docker Compose v2 are required.

```bash
./scripts/bootstrap.sh
```

The first run creates `.env` (passwords), starts Postgres, builds the database, and starts Odoo. Open:

`http://127.0.0.1:18469`

Sign in as **ivari**. The password is `BLURBY_ADMIN_PASSWORD` in `.env`.

Later starts, when the database is already loaded:

```bash
docker compose up -d
```

`./scripts/bootstrap.sh` is safe to repeat. It will not rebuild a database that already finished setup. `./scripts/bootstrap.sh --reconfigure` reloads company data, products, and stock counts without dropping the database.

Stop it with `docker compose down`. That keeps the database. `docker compose down -v` deletes the database and the file store.

## WooCommerce stores

Sales → WooCommerce stores. **Blurby store** and **Hagen store** are inactive until you add their addresses and keys.

| Field | Where it comes from |
| --- | --- |
| Store URL | The shop address, such as `https://blurbybike.com`. Do not append `/wp-json`. |
| Consumer key | WooCommerce → Settings → Advanced → REST API. Create a key with Read/Write permission. |
| Consumer secret | Shown once on that same WooCommerce screen. |

For those two shops, Odoo is the inventory master. Every 15 minutes, an active store with keys pushes sellable quantities to WooCommerce and pulls orders whose status is processing, completed, or the custom status `paid`, and that have a paid date. A kit bike’s sellable quantity is the number that can be built from free components. A bike with no recipe and no finished stock is pushed as zero.

When the payment method matches the shop’s gateway list (Stripe, or WooPayments), the payment is booked on **Stripe Payments** and the invoice is Paid. Any other paid gateway is confirmed and invoiced, and the invoice is left open.

The optional webhook is `POST /hagen/woo/<store id>/<webhook token>`. The token is on the store form. The scheduled sync does not need a public address.

## Rattaproff multisite

Sales → **WooCommerce network**. The network admin is `https://rattaproff.ee`. These shops are separate WooCommerce sites on that one WordPress install, and each already has an inactive store record:

Rattaproff, Fahrrad 7, Cykelpoint.dk, Cykelpoint.se, Rowerkról.pl, Bicinegozio, Velocentras, Bicirey, Velochic, BajkRaj.hr, BajkRaj.cz, BajkRaj.si, BajkRaj.sk, Olabike, Tudobike, BikeRai, Velosklad, Visivelo, Polkimet, Fietsgear.

One WordPress application password covers every shop. On rattaproff.ee, open Users → Profile → Application Passwords as a network super admin, create a password, and paste the username and password on the network form. Discover shops asks WordPress for the live site list and adds any shop that is not in the list above. A shop’s own REST key still overrides the shared password.

Turn a shop active after the password is saved. Paid orders are confirmed and posted as customer invoices. The VAT is the rate Woo charged on that order (the Estonian shop charges 24%), not a flat Hungarian 27%. A line whose SKU is not in Odoo yet is created as a non-stock product so the invoice can still be posted. Stock is not pushed back to these shops, because their catalogs are the stock master.

Euro invoices use the European Central Bank forint rate. The latest fixing loaded with this setup is 1 EUR = 363.90 HUF (6 November 2026). The scheduled sync refreshes that rate when the ECB publishes a new one. NAV stays in Demo, so these invoices are not reported.

## Bike recipes

Manufacturing → Import bike recipes. The file to fill in is `data/bom_recipe_template.csv`.

Columns: `bike_code`, `part_code`, `qty_per_bike`, `bom_type` (`kit` or `manufacture`), `status`, `note`.

Only rows with `status` set to `confirmed`, a part code, and a quantity above zero are loaded. `kit` is a phantom bill of materials: delivering the bike deducts each part and does not open a manufacturing order. `manufacture` opens a manufacturing order and turns on Replenish on Order for that bike, including workshop labour if you add the labour product as a line. Rows that still say `needs_confirmation` are ignored. The current file is entirely unconfirmed because the sheet and the catalog disagree.

## Issuing an invoice

1. Set a sales price on the product (Sales → Products), or type the price on the invoice line.
2. Invoicing → Customers → Invoices → New. Pick the customer and the products. Domestic Hungarian customers get 27% ÁFA (goods tax `F27`, services `F27S`).
3. Confirm, then send. While NAV mode is Demo, Send does not reach the tax authority.

Customer invoices can also be created from a sales order (Sales → Orders). Products are set to invoice on the ordered quantity, so you do not have to validate a delivery first. Stripe orders from WooCommerce do this on their own.

## Connecting NAV

Real Hungarian invoices have to be reported to NAV Online Számla. Do this only when you are ready to file, and only after the tax number and registered seat are confirmed:

1. On the NAV portal, create a technical user with “manage invoices” and “query invoices”, and generate the XML signing key and the XML exchange key.
2. In Odoo: Invoicing → Configuration → Settings → Hungarian Electronic Invoicing.
3. Switch the mode from Demo to Test and check the keys against the NAV test system. When that succeeds, switch to Production.

The company tax number has to stay in the form `25979923-2-41` (optional `HU` prefix) unless the company extract says otherwise. NAV rejects the short EU form `HU25979923`.

The database manager password is `ODOO_MASTER_PASSWORD` in `.env`. The database list is hidden. Changing `.env` after the first bootstrap does not change the `ivari` password; change that in Odoo under the user menu. Restart Odoo after you change the master password and re-render config with `python3 scripts/render_config.py`.

## Versions

Pinned to `odoo:19.0` and `postgres:16`. Odoo 20 is the newer stable line (September 2026). 19 is pinned because the Hungarian invoicing package on 19 has been in use since 2025. Bump the image tag in `docker-compose.yml` when you want to move.
