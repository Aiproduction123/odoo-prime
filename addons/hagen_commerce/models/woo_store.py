import logging
import math
import secrets

import requests

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

PAID_STATUSES = {'processing', 'completed', 'paid'}
SKIP_STATUSES = {'pending', 'failed', 'cancelled', 'refunded', 'on-hold', 'checkout-draft'}


class HagenWooStore(models.Model):
    _name = 'hagen.woo.store'
    _description = 'WooCommerce store'
    _order = 'name'

    name = fields.Char(required=True)
    active = fields.Boolean(default=True)
    company_id = fields.Many2one('res.company', required=True, default=lambda self: self.env.company)
    network_id = fields.Many2one('hagen.woo.network', string='WordPress network', ondelete='set null')
    blog_id = fields.Integer(string='Site id', help='WordPress multisite blog id, when the network reports one.')
    base_url = fields.Char(string='Store URL', help='Shop address, for example https://rattaproff.ee. No trailing /wp-json path.')
    consumer_key = fields.Char(string='Consumer key')
    consumer_secret = fields.Char(string='Consumer secret')
    webhook_token = fields.Char(copy=False, default=lambda self: secrets.token_urlsafe(24))
    warehouse_id = fields.Many2one('stock.warehouse', string='Warehouse')
    payment_gateway = fields.Char(
        default='stripe',
        required=True,
        help='Comma-separated words matched against the WooCommerce payment method id and title.',
    )
    payment_journal_id = fields.Many2one(
        'account.journal',
        string='Stripe journal',
        domain="[('type', 'in', ('bank', 'cash')), ('company_id', '=', company_id)]",
        default=lambda self: self._default_stripe_journal(),
    )
    auto_confirm = fields.Boolean(default=True)
    auto_invoice = fields.Boolean(string='Create and post the invoice', default=True)
    auto_pay = fields.Boolean(string='Register the Stripe payment', default=True)
    stock_sync = fields.Boolean(string='Push stock to this store', default=True)
    last_order_sync = fields.Datetime(readonly=True)
    last_stock_sync = fields.Datetime(readonly=True)
    last_sync_message = fields.Text(readonly=True)

    @api.model
    def _default_stripe_journal(self):
        return self.env['account.journal'].search([
            ('code', '=', 'STRP'),
            ('company_id', '=', self.env.company.id),
        ], limit=1)

    def _auth(self):
        self.ensure_one()
        if self.consumer_key and self.consumer_secret:
            return (self.consumer_key, self.consumer_secret)
        if self.network_id:
            return self.network_id._auth()
        return None

    def _credentials_ok(self):
        self.ensure_one()
        return bool(self.base_url and self._auth())

    def _woo_request(self, method, path, params=None, payload=None):
        self.ensure_one()
        auth = self._auth()
        if not self.base_url or not auth:
            raise UserError(_('Store %s needs a URL and either REST keys or a network application password.') % self.name)
        root = self.base_url.strip().rstrip('/')
        url = f'{root}/wp-json/wc/v3/{path.lstrip("/")}'
        try:
            response = requests.request(
                method,
                url,
                params=params,
                json=payload,
                auth=auth,
                timeout=45,
            )
        except requests.RequestException as error:
            raise UserError(_('Could not reach %s: %s') % (self.name, error)) from error
        if response.status_code >= 400:
            detail = (response.text or '')[:300]
            raise UserError(_('WooCommerce answered %(code)s for %(store)s. %(detail)s') % {
                'code': response.status_code,
                'store': self.name,
                'detail': detail,
            })
        if not response.content:
            return None
        return response.json()

    def action_test_connection(self):
        self.ensure_one()
        self._woo_request('GET', 'products', params={'per_page': 1})
        self.last_sync_message = _('Connection succeeded.')
        return True

    def action_pull_orders(self):
        imported = 0
        for store in self:
            for status in ('processing', 'completed', 'paid'):
                for page in range(1, 21):
                    try:
                        batch = store._woo_request('GET', 'orders', params={
                            'status': status,
                            'per_page': 50,
                            'page': page,
                        }) or []
                    except UserError:
                        if status == 'paid':
                            break
                        raise
                    for payload in batch:
                        try:
                            with store.env.cr.savepoint():
                                order = store._import_paid_order(payload)
                        except Exception:
                            _logger.exception('Skipped WooCommerce order %s from %s', payload.get('id'), store.name)
                            continue
                        if order:
                            imported += 1
                    if len(batch) < 50:
                        break
            store.last_order_sync = fields.Datetime.now()
            store.last_sync_message = _('Imported %s paid orders.') % imported
        return True

    def action_push_stock(self):
        for store in self:
            store._push_stock()
            store.last_stock_sync = fields.Datetime.now()
        return True

    @api.model
    def cron_sync(self):
        self.env['hagen.woo.network']._ensure_ecb_rates()
        for store in self.search([('active', '=', True)]):
            if not store._credentials_ok():
                continue
            try:
                with self.env.cr.savepoint():
                    if store.stock_sync:
                        store._push_stock()
                        store.last_stock_sync = fields.Datetime.now()
                    store.action_pull_orders()
            except Exception as error:
                _logger.exception('WooCommerce sync failed for %s', store.name)
                store.last_sync_message = str(error)[:500]

    def _push_stock(self):
        self.ensure_one()
        parents = []
        variations = {}
        page = 1
        while page <= 30:
            products = self._woo_request('GET', 'products', params={'per_page': 100, 'page': page, 'status': 'publish'}) or []
            for product in products:
                sku = (product.get('sku') or '').strip()
                if sku:
                    parents.append((sku, product['id']))
                if product.get('type') == 'variable':
                    self._collect_variations(product['id'], variations)
            if len(products) < 100:
                break
            page += 1
        self._push_batch('products/batch', parents)
        for parent_id, rows in variations.items():
            self._push_batch(f'products/{parent_id}/variations/batch', rows)
        self.last_sync_message = _('Pushed stock for %s WooCommerce SKUs.') % (len(parents) + sum(len(rows) for rows in variations.values()))

    def _collect_variations(self, parent_id, variations):
        page = 1
        while page <= 10:
            rows = self._woo_request('GET', f'products/{parent_id}/variations', params={'per_page': 100, 'page': page}) or []
            for row in rows:
                sku = (row.get('sku') or '').strip()
                if sku:
                    variations.setdefault(parent_id, []).append((sku, row['id']))
            if len(rows) < 100:
                break
            page += 1

    def _push_batch(self, path, sku_rows):
        updates = []
        for sku, woo_id in sku_rows:
            product = self.env['product.product'].search([
                ('default_code', '=', sku),
                ('company_id', 'in', [False, self.company_id.id]),
            ], limit=1)
            if not product or not product.is_storable:
                continue
            updates.append({
                'id': woo_id,
                'manage_stock': True,
                'stock_quantity': self._qty_for_store(product),
            })
        for start in range(0, len(updates), 50):
            self._woo_request('POST', path, payload={'update': updates[start:start + 50]})

    def _qty_for_store(self, product):
        self.ensure_one()
        warehouse = self.warehouse_id or self.env['stock.warehouse'].search([
            ('company_id', '=', self.company_id.id),
        ], limit=1)
        product = product.with_company(self.company_id).with_context(warehouse_id=warehouse.id)
        boms = self.env['mrp.bom']._bom_find(product, company_id=self.company_id.id, bom_type='phantom')
        bom = boms.get(product)
        if not bom:
            qty = product.free_qty
        else:
            limits = []
            for line in bom.bom_line_ids:
                need = line.product_qty / (bom.product_qty or 1.0)
                if need <= 0:
                    continue
                available = line.product_id.with_company(self.company_id).with_context(warehouse_id=warehouse.id).free_qty
                limits.append(available / need)
            qty = min(limits) if limits else 0.0
        if qty < 0:
            qty = 0.0
        return int(math.floor(qty + 1e-6))

    def _import_paid_order(self, payload):
        self.ensure_one()
        if not payload or not self._is_paid(payload):
            return self.env['sale.order']
        woo_id = str(payload.get('id') or '')
        if not woo_id:
            return self.env['sale.order']
        existing = self.env['sale.order'].search([
            ('hagen_woo_store_id', '=', self.id),
            ('hagen_woo_order_id', '=', woo_id),
        ], limit=1)
        if existing:
            return existing
        partner = self._partner_from_billing(payload.get('billing') or {})
        number = str(payload.get('number') or woo_id)
        order_vals = {
            'partner_id': partner.id,
            'company_id': self.company_id.id,
            'warehouse_id': (self.warehouse_id or self.env['stock.warehouse'].search([
                ('company_id', '=', self.company_id.id),
            ], limit=1)).id,
            'client_order_ref': number,
            'origin': f'WooCommerce {self.name} #{number}',
            'hagen_woo_store_id': self.id,
            'hagen_woo_order_id': woo_id,
            'hagen_woo_number': number,
        }
        pricelist = self._pricelist_for_payload(payload)
        if pricelist:
            order_vals['pricelist_id'] = pricelist.id
        order = self.env['sale.order'].create(order_vals)
        self._add_lines(order, payload)
        if not order.order_line:
            order.unlink()
            return self.env['sale.order']
        if self.auto_confirm and order.state in ('draft', 'sent'):
            order.action_confirm()
        if self.auto_invoice:
            self._invoice_and_pay(order, payload)
        return order

    def _is_paid(self, payload):
        status = (payload.get('status') or '').lower()
        if status in SKIP_STATUSES:
            return False
        if status == 'paid':
            return True
        return status in PAID_STATUSES and bool(payload.get('date_paid'))

    def _gateway_matches(self, payload):
        needles = [part.strip().lower() for part in (self.payment_gateway or 'stripe').split(',') if part.strip()]
        haystack = f"{payload.get('payment_method') or ''} {payload.get('payment_method_title') or ''}".lower()
        return any(needle in haystack for needle in needles)

    def _pricelist_for_payload(self, payload):
        code = (payload.get('currency') or '').upper()
        if not code:
            return self.env['product.pricelist']
        currency = self.env['res.currency'].with_context(active_test=False).search([('name', '=', code)], limit=1)
        if not currency or currency == self.company_id.currency_id:
            return self.env['product.pricelist']
        if not currency.active:
            currency.active = True
        self.env['hagen.woo.network']._ensure_ecb_rates([code])
        pricelist = self.env['product.pricelist'].search([
            ('currency_id', '=', currency.id),
            ('company_id', 'in', [False, self.company_id.id]),
        ], limit=1)
        if not pricelist:
            pricelist = self.env['product.pricelist'].create({
                'name': f'WooCommerce {code}',
                'currency_id': currency.id,
                'company_id': self.company_id.id,
            })
        return pricelist

    def _partner_from_billing(self, billing):
        email = (billing.get('email') or '').strip()
        name = ' '.join(part for part in (billing.get('first_name'), billing.get('last_name')) if part).strip()
        company_name = (billing.get('company') or '').strip()
        display = company_name or name or email or _('WooCommerce customer')
        partner = self.env['res.partner']
        if email:
            partner = self.env['res.partner'].search([
                ('email', '=ilike', email),
                ('parent_id', '=', False),
            ], limit=1)
        if not partner:
            country = self.env['res.country'].search([('code', '=', (billing.get('country') or '').upper())], limit=1)
            partner = self.env['res.partner'].create({
                'name': display,
                'email': email or False,
                'phone': billing.get('phone') or False,
                'street': billing.get('address_1') or False,
                'street2': billing.get('address_2') or False,
                'city': billing.get('city') or False,
                'zip': billing.get('postcode') or False,
                'country_id': country.id,
                'is_company': bool(company_name),
                'lang': 'hu_HU' if country.code == 'HU' else 'en_US',
                'company_id': self.company_id.id,
            })
        return partner

    def _add_lines(self, order, payload):
        OrderLine = self.env['sale.order.line']
        for item in payload.get('line_items') or []:
            qty = float(item.get('quantity') or 0)
            if qty <= 0:
                continue
            sku = (item.get('sku') or '').strip()
            if not sku:
                sku = f"WOO-{item.get('product_id') or item.get('id') or 'line'}"
            product = self._product_for_line(sku, item.get('name'))
            total = float(item.get('total') or 0)
            line = OrderLine.create({
                'order_id': order.id,
                'product_id': product.id,
                'product_uom_qty': qty,
            })
            line.price_unit = total / qty
            tax = self._tax_for_item(payload, item)
            if tax is not None:
                line.tax_ids = tax
        shipping = float(payload.get('shipping_total') or 0)
        if shipping:
            product = self._shipping_product()
            line = OrderLine.create({
                'order_id': order.id,
                'product_id': product.id,
                'product_uom_qty': 1,
            })
            line.price_unit = shipping
            if 'shipping_tax' in payload or payload.get('tax_lines'):
                rate = self._single_order_rate(payload)
                if rate is None:
                    rate = self._percent(shipping, payload.get('shipping_tax'))
                line.tax_ids = self._tax_for_rate(rate)

    def _product_for_line(self, sku, name):
        product = self.env['product.product'].search([
            ('default_code', '=', sku),
            ('company_id', 'in', [False, self.company_id.id]),
        ], limit=1)
        if product:
            return product
        template = self.env['product.template'].create({
            'name': name or sku,
            'default_code': sku,
            'type': 'consu',
            'is_storable': False,
            'invoice_policy': 'order',
            'list_price': 0.0,
            'taxes_id': [(6, 0, [])],
            'supplier_taxes_id': [(6, 0, [])],
        })
        return template.product_variant_id

    def _tax_for_item(self, payload, item):
        """Return the sale tax Woo charged, or None to keep the product tax."""
        if 'total_tax' not in item and not item.get('taxes'):
            return None
        rate_ids = {row.get('id') for row in (item.get('taxes') or []) if isinstance(row, dict)}
        for tax_line in payload.get('tax_lines') or []:
            if tax_line.get('rate_id') in rate_ids and tax_line.get('rate_percent') is not None:
                return self._tax_for_rate(float(tax_line['rate_percent']))
        return self._tax_for_rate(self._percent(item.get('total'), item.get('total_tax')))

    def _single_order_rate(self, payload):
        percents = [
            round(float(row['rate_percent']), 2)
            for row in payload.get('tax_lines') or []
            if row.get('rate_percent') is not None
        ]
        unique = set(percents)
        if len(unique) == 1:
            return unique.pop()
        return None

    def _percent(self, net, tax_amount):
        net = float(net or 0)
        tax_amount = float(tax_amount or 0)
        if abs(net) < 1e-9:
            return 0.0
        return round(tax_amount / net * 100, 2)

    def _tax_for_rate(self, percent):
        percent = round(float(percent or 0), 2)
        taxes = self.env['account.tax'].search([
            ('company_id', '=', self.company_id.id),
            ('type_tax_use', '=', 'sale'),
            ('amount_type', '=', 'percent'),
            ('price_include', '=', False),
            ('active', '=', True),
        ])
        for tax in taxes:
            if abs(tax.amount - percent) < 0.05:
                return tax
        sample = taxes[:1]
        return self.env['account.tax'].create({
            'name': f'VAT {percent:g}%',
            'amount': percent,
            'amount_type': 'percent',
            'type_tax_use': 'sale',
            'price_include_override': 'tax_excluded',
            'company_id': self.company_id.id,
            'country_id': sample.country_id.id,
            'tax_group_id': sample.tax_group_id.id,
        })

    def _shipping_product(self):
        product = self.env['product.product'].search([('default_code', '=', 'WOO-SHIP')], limit=1)
        if product:
            return product
        tax = self.env['account.chart.template'].with_company(self.company_id).ref('F27S', raise_if_not_found=False)
        template = self.env['product.template'].create({
            'name': 'WooCommerce shipping',
            'default_code': 'WOO-SHIP',
            'type': 'service',
            'list_price': 0.0,
            'invoice_policy': 'order',
            'taxes_id': [(6, 0, tax.ids)] if tax else False,
        })
        return template.product_variant_id

    def _invoice_and_pay(self, order, payload):
        if order.invoice_status != 'to invoice' and not order.invoice_ids:
            return
        invoices = order.invoice_ids.filtered(lambda move: move.state != 'cancel' and move.move_type == 'out_invoice')
        if not invoices:
            invoices = order._create_invoices()
        drafts = invoices.filtered(lambda move: move.state == 'draft')
        if drafts:
            drafts.action_post()
        if not self.auto_pay or not self._gateway_matches(payload):
            if not self._gateway_matches(payload):
                order.message_post(body=_('Payment gateway does not match this shop, so the invoice was left open.'))
            return
        journal = self.payment_journal_id or self._default_stripe_journal()
        if not journal:
            raise UserError(_('Set the Stripe journal on %s.') % self.name)
        for invoice in invoices.filtered(lambda move: move.state == 'posted' and move.payment_state not in ('paid', 'in_payment')):
            wizard = self.env['account.payment.register'].with_context(
                active_model='account.move',
                active_ids=invoice.ids,
            ).create({'journal_id': journal.id})
            wizard._create_payments()
