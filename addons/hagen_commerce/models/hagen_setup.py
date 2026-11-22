import logging
import os

from odoo import api, models

_logger = logging.getLogger(__name__)

# Standalone framesets sold on the Hagen webshops. The SKU is the internal
# reference, which has to equal the WooCommerce SKU.
FRAMESETS = (
    ('FS-HAGEN-FLAGSHIP', 'Hagen Flagship frameset'),
    ('FS-HAGEN-XL', 'Hagen XL frameset'),
)
FRAMESET_DESCRIPTION = (
    'Non-electric kit: frame, Hagen fork A65, 4 headset bearings A96, 2 bearings A131, kickstand and '
    'steering rod A161. Website extras are added as separate order lines. Sale price is not set.'
)
# Hagen Mini is discontinued and framesets are sold non-electric only.
RETIRED = ('A59', 'A60', 'FS-HAGEN-MINI', 'FS-HAGEN-MINI-E', 'FS-HAGEN-FLAGSHIP-E', 'FS-HAGEN-XL-E')

NEW_PARTS = (
    ('A154', 'Hagen rear wheel — 29" (10-speed cassette, standard)', 'Hagen parts'),
    ('A155', 'Hagen front wheel — 20" (non-dynamo)', 'Hagen parts'),
    ('A156', 'Shifter — Shimano Deore 10-speed', 'Bike parts'),
    ('A157', 'Hagen rear wheel — Shimano Nexus 5-speed', 'Hagen parts'),
    ('A158', 'Shifter — Shimano Nexus 5-speed', 'Bike parts'),
    ('A159', 'Hagen rear wheel — Shimano Alfine 8-speed', 'Hagen parts'),
    ('A160', 'Shifter — Shimano Alfine 8-speed', 'Bike parts'),
    ('A161', 'Hagen steering rod', 'Hagen parts'),
    ('A162', 'Blurby controller', 'Blurby electronics'),
)

COMPANY_VAT = '25979923-2-43'
COMPANY_SEAT = {'street': 'Öntő utca 5.', 'street2': False, 'zip': '1211', 'city': 'Budapest'}

STOCK_MASTER_SHOPS = (
    ('Blurby store', 'https://blurbybike.com'),
    ('Hagen store', 'https://hagenbikes.com'),
)

EMPLOYEE_LOGIN = 'workshop'
EMPLOYEE_APPS = ('sale.sale_menu_root', 'stock.menu_stock_root', 'mrp.menu_mrp_root')
# Menus inside the three apps that lead to invoicing or settings.
EMPLOYEE_HIDDEN = (
    'sale.menu_sale_invoicing',
    'sale.menu_sale_report',
    'stock.menu_stock_config_settings',
    'stock.menu_valuation',
    'stock_account.menu_valuation',
    'mrp.menu_mrp_reporting',
    'mrp.menu_mrp_configuration',
)


class HagenSetup(models.AbstractModel):
    _name = 'hagen.setup'
    _description = 'Hagen Group setup that is safe to repeat'

    @api.model
    def run(self):
        self._company_seat()
        self._store_addresses()
        self._new_parts()
        self._framesets()
        self._retire()
        self._labour_hours()
        self._receipts()
        employee = self._employee_user()
        self._employee_menus(employee)
        self._opening_count_lines()
        return True

    def _store_addresses(self):
        Store = self.env['hagen.woo.store'].with_context(active_test=False)
        for name, url in STOCK_MASTER_SHOPS:
            store = Store.search([('name', '=', name), ('company_id', '=', self.env.company.id)], limit=1)
            if store and not store.base_url:
                store.base_url = url

    def _company_seat(self):
        company = self.env.company.sudo()
        if not company.partner_id.country_id or company.partner_id.country_id.code != 'HU':
            return
        values = {key: value for key, value in COMPANY_SEAT.items() if company[key] != value}
        if company.vat != COMPANY_VAT:
            values['vat'] = COMPANY_VAT
        if 'hagen_nav_extract_confirmed' in company._fields and not company.hagen_nav_extract_confirmed:
            values['hagen_nav_extract_confirmed'] = True
        if values:
            company.write(values)
        if 'company_details' in company._fields and company.company_details and 'Kecskeméti' in company.company_details:
            company.company_details = (
                '<p>Hagen Group Kft.<br/>1211 Budapest, Öntő utca 5.<br/>Cégjegyzékszám: %s<br/>'
                'Adószám: %s<br/>info@blurbybike.com</p>'
            ) % (company.company_registry or '01-09-299788', COMPANY_VAT)
        workshop = self.env['res.partner'].search([
            ('name', '=', 'Hagen Group workshop'), ('parent_id', '=', company.partner_id.id),
        ], limit=1)
        if workshop and workshop.comment and 'Kecskeméti' in str(workshop.comment):
            workshop.comment = 'Service workshop at the registered seat.'

    def _new_parts(self):
        sale_tax, purchase_tax = self._goods_taxes()
        Template = self.env['product.template'].with_context(active_test=False)
        for code, name, category_name in NEW_PARTS:
            if Template.search([('default_code', '=', code)], limit=1):
                continue
            category = self.env['product.category'].search([('name', '=', category_name)], limit=1)
            if not category:
                category = self.env['product.category'].create({'name': category_name})
            vals = {
                'name': name,
                'default_code': code,
                'categ_id': category.id,
                'type': 'consu',
                'is_storable': True,
                'sale_ok': True,
                'purchase_ok': True,
                'invoice_policy': 'order',
                'list_price': 0.0,
                'description': 'New part in 2026. Sale price is not set. Put the real price on the product before invoicing.',
            }
            if sale_tax:
                vals['taxes_id'] = [(6, 0, sale_tax.ids)]
            if purchase_tax:
                vals['supplier_taxes_id'] = [(6, 0, purchase_tax.ids)]
            Template.create(vals)

    def _retire(self):
        templates = self.env['product.template'].with_context(active_test=False).search([('default_code', 'in', RETIRED)])
        if not templates:
            return
        boms = self.env['mrp.bom'].with_context(active_test=False).search([('product_tmpl_id', 'in', templates.ids)])
        drafts = boms.filtered(lambda bom: not bom.active and bom.code == 'Draft for sign-off')
        (boms - drafts).filtered('active').write({'active': False})
        drafts.unlink()
        quants = self.env['stock.quant'].sudo().search([
            ('product_id', 'in', templates.with_context(active_test=False).product_variant_ids.ids),
            ('quantity', '=', 0), ('reserved_quantity', '=', 0),
        ])
        quants.unlink()
        templates.filtered('active').write({'active': False})

    def _labour_hours(self):
        hours = self.env.ref('uom.product_uom_hour', raise_if_not_found=False)
        labour = self.env['product.template'].search([('default_code', '=', 'SVC-LABOUR')], limit=1)
        if not hours or not labour or labour.uom_id == hours:
            return
        lines = self.env['mrp.bom.line'].with_context(active_test=False).search([('product_tmpl_id', '=', labour.id)])
        labour.uom_id = hours
        lines.write({'product_uom_id': hours.id})

    def _goods_taxes(self):
        chart = self.env['account.chart.template'].with_company(self.env.company)
        sale = chart.ref('F27', raise_if_not_found=False)
        purchase = chart.ref('V27', raise_if_not_found=False)
        return sale, purchase

    def _framesets(self):
        category = self.env['product.category'].search([('name', '=', 'Hagen framesets')], limit=1)
        if not category:
            category = self.env['product.category'].create({'name': 'Hagen framesets'})
        sale_tax, purchase_tax = self._goods_taxes()
        Template = self.env['product.template'].with_context(active_test=False)
        for code, name in FRAMESETS:
            vals = {
                'name': name,
                'default_code': code,
                'categ_id': category.id,
                'type': 'consu',
                'is_storable': True,
                'sale_ok': True,
                'purchase_ok': False,
                'invoice_policy': 'order',
                'description': FRAMESET_DESCRIPTION,
            }
            if sale_tax:
                vals['taxes_id'] = [(6, 0, sale_tax.ids)]
            if purchase_tax:
                vals['supplier_taxes_id'] = [(6, 0, purchase_tax.ids)]
            template = Template.search([('default_code', '=', code)], limit=1)
            if template:
                template.write({key: value for key, value in vals.items() if key != 'name'})
            else:
                Template.create({**vals, 'list_price': 0.0})

    def _receipts(self):
        receipts = self.env['stock.picking.type'].search([
            ('code', '=', 'incoming'),
            ('company_id', '=', self.env.company.id),
        ])
        receipts.write({'create_backorder': 'always'})

    def _employee_user(self):
        group = self.env.ref('hagen_commerce.group_employee')
        Users = self.env['res.users'].with_context(active_test=False, no_reset_password=True)
        user = Users.search([('login', '=', EMPLOYEE_LOGIN)], limit=1)
        home = self.env.ref('stock.stock_picking_type_action', raise_if_not_found=False)
        if not user:
            user = Users.create({
                'name': 'Workshop (Öntő utca)',
                'login': EMPLOYEE_LOGIN,
                'email': False,
                'company_id': self.env.company.id,
                'company_ids': [(6, 0, self.env.company.ids)],
                'group_ids': [(6, 0, group.ids)],
                'tz': 'Europe/Budapest',
                'lang': 'en_US',
                'action_id': home.id if home else False,
            })
            password = os.environ.get('HAGEN_EMPLOYEE_PASSWORD')
            if password:
                user.password = password
            else:
                _logger.warning('HAGEN_EMPLOYEE_PASSWORD is not set; set the workshop password in Settings → Users.')
        else:
            user.write({'group_ids': [(4, group.id)]})
        return user

    def _employee_menus(self, employee):
        """Leave only Sales, Inventory and Manufacturing on the employee home screen."""
        office = self.env.ref('hagen_commerce.group_office')
        allowed = self.env['ir.ui.menu']
        for xmlid in EMPLOYEE_APPS:
            allowed |= self.env.ref(xmlid, raise_if_not_found=False) or self.env['ir.ui.menu']
        Menu = self.env['ir.ui.menu'].with_user(employee)
        visible = Menu.browse(Menu._visible_menu_ids()).sudo()
        to_hide = visible.filtered(lambda menu: not menu.parent_id and menu not in allowed)
        for xmlid in EMPLOYEE_HIDDEN:
            menu = self.env.ref(xmlid, raise_if_not_found=False)
            if menu and menu in visible:
                to_hide |= menu
        employee_groups = employee.all_group_ids
        for menu in to_hide.sudo():
            menu.group_ids = [(6, 0, ((menu.group_ids - employee_groups) | office).ids)]
        self.env.registry.clear_cache()

    def _opening_count_lines(self):
        """Put every part, bike and frameset part on the Physical Inventory screen, ready to count."""
        warehouse = self.env['stock.warehouse'].search([('company_id', '=', self.env.company.id)], limit=1)
        if not warehouse:
            return
        location = warehouse.lot_stock_id
        products = self.env['product.product'].search([
            ('is_storable', '=', True),
            '|', ('default_code', '=like', 'A%'), ('default_code', '=like', 'M-%'),
        ])
        Quant = self.env['stock.quant'].with_context(inventory_mode=True)
        existing = set(Quant.search([('location_id', '=', location.id), ('product_id', 'in', products.ids)]).product_id.ids)
        for product in products:
            if product.id not in existing:
                Quant.create({'product_id': product.id, 'location_id': location.id})
