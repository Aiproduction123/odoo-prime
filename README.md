# Hagen Group ERP

Self-hosted [Odoo 19 Community](https://www.odoo.com/) for **Hagen Group Kft.** (formerly BLURBY Korlátolt Felelősségű Társaság). It covers Hungarian invoicing, purchasing and receiving, the parts catalog, bike recipes, a simple workshop login, and a multi-store WooCommerce connector that treats Odoo as the stock master.

Everything used here is in Community: Invoicing, the Hungarian chart of accounts (27% / 18% / 5% ÁFA), Sales, Purchase, Inventory, Manufacturing, and the NAV 3.0 e-invoicing module. NAV is **not** connected. The company stays in **Demo** mode, which mocks the tax authority and files nothing, and Odoo refuses to leave Demo until the company extract has been confirmed on the NAV go-live form (see [NAV](#nav-e-invoicing)).

The one-page staff cheat sheet is [`docs/employee_sop.md`](docs/employee_sop.md) (print `docs/employee_sop.html`).

## What is already filled in

| | |
| --- | --- |
| Legal name | Hagen Group Kft. |
| Seat on invoices | 1053 Budapest, Kecskeméti utca 5. |
| Workshop | 1211 Budapest, Öntő utca 5. (delivery address on the company) |
| Company register | 01-09-299788 |
| Tax number kept on the company | 25979923-2-41 (to be confirmed, see NAV) |
| Currency | HUF; EUR invoices use the ECB rate |
| Admin login | `ivari` (Ivari Kull). Password: `BLURBY_ADMIN_PASSWORD` in `.env`. |
| Workshop login | `workshop`, “Workshop (Öntő utca)”. Password: `HAGEN_EMPLOYEE_PASSWORD` in `.env`. |
| Stripe journal | Bank journal **Stripe Payments**, code `STRP` |

Products: parts A1–A153 and bikes M-001–M-008 are storable. The framesets FS-HAGEN-FLAGSHIP, FS-HAGEN-FLAGSHIP-E, FS-HAGEN-XL and FS-HAGEN-XL-E are storable kits. Workshop labour SVC-LABOUR is a service. Sales prices are empty on purpose.

## Run it

Docker and Docker Compose v2 are required.

```bash
./scripts/bootstrap.sh
```

The first run creates `.env` (random passwords for the database, the database manager, `ivari` and `workshop`), starts Postgres, builds the database and starts Odoo at `http://127.0.0.1:18469`.

| Command | What it does |
| --- | --- |
| `docker compose up -d` | Start again after a reboot. |
| `./scripts/bootstrap.sh --upgrade` | Load a new version of the Hagen module (and install Purchase if missing). Keeps all data. |
| `./scripts/bootstrap.sh --reconfigure` | Reload company data and products without dropping the database. |
| `docker compose down` | Stop. Keeps the database. `down -v` deletes it. |

## Office computer and this laptop

Odoo listens on port **18469** on every network address of the machine that runs Docker. `./scripts/office_url.sh` prints the addresses to open from another computer, such as `http://192.168.1.20:18469`. Any number of people can be signed in at the same time, from any computer, with the same or different logins.

If the office computer cannot connect, the machine running Docker is blocking the port: `sudo ufw allow 18469/tcp` on Linux, or allow inbound TCP 18469 on private networks on Windows.

From outside the office, a Cloudflare quick tunnel works without opening the router:

```bash
cloudflared tunnel --no-autoupdate --url http://127.0.0.1:18469
```

It prints a `https://….trycloudflare.com` address that changes every time it starts. For a fixed address, create a named tunnel in the Cloudflare dashboard.

## Who sees what

| | `ivari` (administrator, group **Office**) | `workshop` (group **Workshop employee**) |
| --- | --- | --- |
| Apps | All | Sales, Inventory, Manufacturing |
| Receive parts, build bikes, ship orders | Yes | Yes |
| Cost, purchase prices, vendor tab, vendor price list | Yes | Hidden |
| Purchase orders, vendor bills, payments, Invoicing | Yes | Hidden |
| Settings, Configuration menus, reporting, WooCommerce stores, recipe import | Yes | Hidden |

Add more staff under Settings → Users & Companies → Users: set **Hagen Group** to *Workshop employee*, and give them no other app rights. The `workshop` user opens on Inventory → Overview.

## Receiving parts

Receipts create a backorder automatically when fewer parts arrive than ordered. No question is asked.

- **Against a purchase order** (office creates it under Purchase → Orders): Inventory → Overview → **Receipts** → open the receipt → type the quantity that arrived → **Validate**.
- **Without a purchase order:** Inventory → Overview → **Receipts** → **New** → add the parts and quantities → **Validate**.

Validating updates on-hand stock at once. The webshop numbers follow on the next 15-minute sync.

## Opening Inventory 2026 and the webshop gate

All 22 webshops are switched off. Odoo refuses to switch a stock-master shop (Blurby, Hagen) on, and refuses to push stock, until the opening count has been applied. This stops Odoo from pushing zeros or the old spreadsheet numbers to the live shops.

1. Print or share `data/opening_inventory_2026.csv`. It lists every part, bike and frameset at WH/Stock with the 2025-12-31 sheet quantity for reference. Fill `counted_qty` on the shelf. Leave a row blank if it was not counted, so it is never set to zero. Leave the four FS-HAGEN rows blank, because framesets are counted as parts.
2. Either type the counts in Inventory → Operations → **Physical Inventory** (every part already has a line), or copy the file into `data/` and run:

   ```bash
   sudo docker compose exec -T odoo odoo shell -d blurby --no-http < scripts/load_opening_counts.py
   ```

   The script only fills the Counted column. It never applies anything.
3. Check the differences on Physical Inventory, then click **Apply All** and keep the reference **Opening Inventory 2026**. That opens the gate.
4. Sales → WooCommerce stores → open each shop → tick **Active**.

## Bike recipes and framesets

Manufacturing → Import bike recipes (administrator), file `data/bom_recipe_template.csv`. To reload it from the command line:

```bash
sudo docker compose exec -T odoo odoo shell -d blurby --no-http < scripts/import_recipes.py
```

Columns: `bike_code, part_code, qty_per_bike, bom_type, status, sheet_code, note`.

| `status` | Effect |
| --- | --- |
| `confirmed` | Goes into the live recipe (reference “Confirmed recipe”). |
| `inferred` | Goes only into an archived draft recipe (reference “Draft for sign-off”, together with the confirmed lines). Find drafts under Manufacturing → Products → Bills of Materials → Filters → Archived. To approve a line, change it to `confirmed` and import again. |
| `needs_confirmation`, `needs_new_part` | Ignored until answered. |

`bom_type`: `kit` ships the parts with the order and needs no manufacturing order (framesets, which are assembled when shipped). `manufacture` is a pre-assembled bike. A sale creates a manufacturing order (Manufacture + Replenish on Order), the parts are consumed when the order is marked Done, and an SVC-LABOUR line adds labour cost without a stock move.

Each sheet code in the 2025-12-31 workbook's recipe blocks is one row too high (A50 for A49, A62 for A61, and so on). The CSV keeps the sheet's code in `sheet_code` and the corrected code in `part_code`.

**One parts pool.** “Sellable on webshops” on every product is the free stock plus what the free parts can still build. Framesets and complete bikes draw on the same frames, A65 forks and A96 bearings, so selling a FS-HAGEN-FLAGSHIP frameset lowers the M-005 number straight away, and the other way round. That number is what Odoo pushes to the Blurby and Hagen shops.

## WooCommerce stores

Sales → WooCommerce stores. **Blurby store** (`https://blurbybike.com`) and **Hagen store** (`https://hagenbikes.com`) have their addresses filled in. Both are off, and neither has keys yet.

| Field | Where it comes from |
| --- | --- |
| Consumer key / secret | WooCommerce → Settings → Advanced → REST API → Add key, Read/Write. The secret is shown once. |
| Test connection | Button on the store form. It reads one product and changes nothing. |

When a store is active, every 15 minutes it pushes “Sellable on webshops” to products whose Woo SKU equals the Odoo code, and pulls orders that are processing, completed or `paid` with a paid date. Stripe or WooPayments orders get 27% ÁFA (or the rate Woo charged), the payment is booked on **STRP**, and the invoice is Paid. Any other gateway, such as bank transfer or GiroCode, is invoiced and left open.

hagenbikes.com sells bikes through a configurator. The order line is “Hagen FLAGSHIP” or “Hagen XL” with no SKU, and the choice is in the line options. Odoo maps those lines as follows:

| Order line | Odoo product |
| --- | --- |
| FLAGSHIP, Type “Non-electric” / “Nicht-elektrisch” | M-005 |
| FLAGSHIP, Type “90 Nm Brose Mid-Motor” | M-006 |
| XL, Non-electric | M-007 |
| XL, 90 Nm Brose | M-008 |
| FLAGSHIP / XL, Type “Frame set” | FS-HAGEN-FLAGSHIP / FS-HAGEN-XL (`-E` if the option says electric) |
| MINI | No Odoo product yet. Invoiced as a non-stock line. |

Configurator products have no stock per Type in WooCommerce, so the stock push cannot reach them. To push bike and frameset stock, give each Type its own SKU equal to the Odoo code, or make them variations with those SKUs.

hagenbikes.com is behind a Cloudflare bot check (“Just a moment…”), which can also block Odoo's REST calls. If **Test connection** fails with HTTP 403, add a WAF skip rule for `/wp-json/wc/` from the office's public IP address.

The optional webhook is `POST /hagen/woo/<store id>/<webhook token>`. The scheduled sync does not need a public address.

## Rattaproff multisite

Sales → **WooCommerce network** → Rattaproff network (`https://rattaproff.ee`), with 20 shops already listed: Rattaproff, Fahrrad 7, Cykelpoint.dk, Cykelpoint.se, Rowerkról.pl, Bicinegozio, Velocentras, Bicirey, Velochic, BajkRaj.hr, BajkRaj.cz, BajkRaj.si, BajkRaj.sk, Olabike, Tudobike, BikeRai, Velosklad, Visivelo, Polkimet, Fietsgear.

1. On rattaproff.ee, as a network super admin: Users → Profile → Application Passwords → add one named “Odoo”.
2. Paste the username and the password on the network form, save, then click **Test connection**. It reads one order from each shop and imports nothing. The result is under Last check.
3. Switch shops on once the opening inventory is applied.

Paid orders become posted customer invoices with the VAT Woo charged (the Estonian shop charges 24%) in the order's currency at the ECB rate, and card payments are booked on STRP. Unknown SKUs are created as non-stock products. Stock is not pushed to these shops. rattaproff.ee blocks XML-RPC, so **Discover shops** cannot read the site list; add new shops with New on WooCommerce stores.

## NAV e-invoicing

NAV stays in **Demo** until two things are done.

1. **Company extract.** The database uses `25979923-2-41` with seat 1053 Budapest, Kecskeméti utca 5. Later dealership documents use `25979923-2-43` with seat 1211 Budapest, Öntő utca 5. Check the current cégkivonat to see which pair is right.
2. **Technical user.** On onlineszamla.nav.gov.hu → Felhasználók, create a technical user with invoice manage and query rights. Note the username, password, XML signing key (aláírókulcs) and XML exchange key (cserekulcs).

Then: Invoicing → Configuration → **NAV go-live** (administrator only). Pick the tax number, which also sets the matching seat. Tick the extract confirmation, enter the four credentials, choose Production (or Test with a separate test-portal user), and click **Switch NAV**. Odoo runs a NAV token exchange before saving, which files nothing. If NAV rejects the credentials, nothing changes and the mode stays Demo. Switching the mode directly in Settings is blocked until the form has been used.

`scripts/check_nav_demo.py` posts two test invoices (HUF B2B, EUR B2C), builds their NAV 3.0 XML, validates it against the official schema (download it once with `./scripts/fetch_nav_xsd.sh`) and runs the Demo upload, then rolls everything back.

## Checks

All of these run against the live database. The `odoo shell` ones roll back their test data.

```bash
python3 scripts/verify.py
sudo docker compose exec -T odoo odoo shell -d blurby --no-http < scripts/check_workshop_flow.py
sudo docker compose exec -T odoo odoo shell -d blurby --no-http < scripts/check_hagen_flow.py
sudo docker compose exec -T odoo odoo shell -d blurby --no-http < scripts/check_nav_demo.py
```

`check_workshop_flow.py` signs in as the workshop user. It receives parts with and without a purchase order (with a backorder), sells a frameset and a bike from the same parts, finishes the manufacturing order, and checks that costs and the webshop gate stay locked. `check_hagen_flow.py` covers Woo order import, Stripe vs bank transfer, the configurator mapping, Rattaproff EUR invoices and kit deliveries.

The database manager password is `ODOO_MASTER_PASSWORD` in `.env`. Changing `.env` after the first bootstrap does not change existing user passwords; change those in Odoo.

## Versions

Pinned to `odoo:19.0` and `postgres:16`. Bump the image tag in `docker-compose.yml` to move.
