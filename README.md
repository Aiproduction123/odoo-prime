# Blurby invoicing

Self-hosted [Odoo 19 Community](https://www.odoo.com/) for **BLURBY Korlátolt Felelősségű Társaság**, with Hungarian invoicing and the parts catalog from the company inventory sheet.

Odoo here is the Community edition. The Invoicing app, the Hungarian chart of accounts (27% / 18% / 5% ÁFA), and the NAV 3.0 e-invoicing module are all in Community. NAV itself is not connected yet: the company is in **demo** mode, which mocks the tax authority and does not file anything.

## What is already filled in

| | |
| --- | --- |
| Legal name | BLURBY Korlátolt Felelősségű Társaság |
| Seat | 1053 Budapest, Kecskeméti utca 5. |
| Workshop | 1211 Budapest, Öntő utca 5. (delivery address on the company) |
| Company register | 01-09-299788 |
| Tax number | 25979923-2-41 |
| Currency | HUF |
| Email on documents | info@blurbybike.com |
| Sign-in | Ivari Kull, `ivari@blurbybike.com`. Screens are in English. Hungarian is installed; switch it under the user menu → Preferences. |

Installed apps: **Invoicing**, **Sales**, **Inventory**. Parts A1–A153 are products, with the on-hand counts from the inventory sheet (last updated 27 May 2026). Bike models M-001–M-008 and a workshop labour service are there too. Sales prices are empty on purpose. One sample draft invoice (Blurby Trekking, 10,000 Ft + 27% ÁFA) shows the tax math. Delete that draft and the “Sample customer (delete me)” contact before the first real invoice.

Not loaded: historical invoices, bank accounts, NAV technical-user keys, or the 1,200 figure on Blurby Trekking (the sheet does not say which currency).

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

## Issuing an invoice

1. Set a sales price on the product (Sales → Products), or type the price on the invoice line.
2. Invoicing → Customers → Invoices → New. Pick the customer and the products. Domestic Hungarian customers get 27% ÁFA (goods tax `F27`, services `F27S`).
3. Confirm, then send. While NAV mode is Demo, Send does not reach the tax authority.

Customer invoices can also be created from a sales order (Sales → Orders). Products are set to invoice on the ordered quantity, so you do not have to validate a delivery first.

## Connecting NAV

Real Hungarian invoices have to be reported to NAV Online Számla. Do this only when you are ready to file:

1. On the NAV portal, create a technical user with “manage invoices” and “query invoices”, and generate the XML signing key and the XML exchange key.
2. In Odoo: Invoicing → Configuration → Settings → Hungarian Electronic Invoicing.
3. Switch the mode from Demo to Test and check the keys against the NAV test system. When that succeeds, switch to Production.

The company tax number has to stay in the form `25979923-2-41` (optional `HU` prefix). NAV rejects the short EU form `HU25979923`.

The database manager password is `ODOO_MASTER_PASSWORD` in `.env`. The database list is hidden. Changing `.env` after the first bootstrap does not change the `ivari` password; change that in Odoo under the user menu. Restart Odoo after you change the master password and re-render config with `python3 scripts/render_config.py`.

## Versions

Pinned to `odoo:19.0` and `postgres:16`. Odoo 20 is the newer stable line (September 2026). 19 is pinned because the Hungarian invoicing package on 19 has been in use since 2025. Bump the image tag in `docker-compose.yml` when you want to move.
