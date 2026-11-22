# Hagen Group workshop cheat sheet

Öntő utca 5., 1211 Budapest · Odoo login: **workshop** · Hungarian screen names in [brackets]

Open Odoo, sign in, and you land on **Inventory → Overview** [Készlet → Áttekintés]. You only see three apps: **Sales** [Értékesítés], **Inventory** [Készlet], **Manufacturing** [Gyártás]. Prices and supplier bills are not shown to you. That is on purpose.

## 1. Receiving new parts

**A. Delivery we ordered (there is a purchase order)**

1. Inventory → Overview → **Receipts** [Beszállítások] card → open the line with the supplier's name.
2. In **Quantity** [Mennyiség], type what is really in the box. Change only the lines that differ.
3. Click **Validate** [Jóváhagyás].

If less arrived than ordered, Odoo keeps the rest open as a new receipt (backorder [visszamaradt rendelés]) by itself. Do not cancel it.

**B. Parts arrive with no order (direct receipt)**

1. Inventory → Overview → **Receipts** [Beszállítások] → **New** [Új].
2. **Receive From** [Partner]: the supplier. **Add a line** [Új sor]: part code (e.g. A65) and quantity. Repeat for each part.
3. Click **Validate** [Jóváhagyás].

Stock updates at once. The webshops show the new numbers within 15 minutes. Put the parts on their shelf before the next job.

## 2. Building a bike

1. Manufacturing → **Manufacturing Orders** [Gyártási rendelések]. Webshop orders for complete bikes create these by themselves.
2. Open the order. Check **Components** [Komponensek]: green means the parts are in stock. Red means a part is missing, so tell the office before you start.
3. Build the bike. If you used a different quantity of a part, correct it on its line.
4. Click **Produce All** (if shown), then **Validate** [Jóváhagyás] until the status says **Done** [Kész].

Done removes the parts from stock and adds 1 finished bike. Never mark an order Done before the bike is really built.

## 3. Fulfilling a webshop order

1. Inventory → Overview → **Delivery Orders** [Szállítólevelek] card → open the order. **Source Document** [Forrás dokumentum] shows the sales order and webshop number.
2. Status **Ready** [Előkészítve]: all items are in stock. **Waiting** [Várakozó]: a bike is still being built (section 2) or parts are missing.
3. Pack exactly the listed lines. A frameset order lists frame, fork (A65) and headset bearings (A96): they go in the same box.
4. Click **Validate** [Jóváhagyás]. Write the order number on the box.

## Rules

- Never type a quantity you did not count. When unsure, ask the office first.
- Broken part: Inventory → Operations → **Scrap** [Selejt], not a delete.
- Shelf count (Opening Inventory 2026): Inventory → Operations → **Physical Inventory** [Fizikai leltár]. Type the **Counted Quantity** [Számolt mennyiség] only. The office clicks **Apply All** [Összes alkalmazása].
- Something looks wrong? Stop, do not click Validate, and call Ivari.
