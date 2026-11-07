import logging
import xml.etree.ElementTree as ET
from xml.sax.saxutils import escape

import requests

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

ECB_DAILY = 'https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml'
ECB_NS = {'gesmes': 'http://www.gesmes.org/xml/2002-08-01', 'e': 'http://www.ecb.int/vocabulary/2002-08-01/eurofxref'}

# Public shops on the rattaproff.ee WordPress multisite. Each one has its own
# WooCommerce orders, keys, and VAT. The network admin lives on rattaproff.ee.
RATTAPROFF_SHOPS = (
    ('https://rattaproff.ee', 'Rattaproff'),
    ('https://fahrrad7.de', 'Fahrrad 7'),
    ('https://cykelpoint.dk', 'Cykelpoint.dk'),
    ('https://cykelpoint.se', 'Cykelpoint.se'),
    ('https://rowerkrol.pl', 'Rowerkról.pl'),
    ('https://bicinegozio.it', 'Bicinegozio'),
    ('https://velocentras.lt', 'Velocentras'),
    ('https://bicirey.es', 'Bicirey'),
    ('https://velochic.fr', 'Velochic'),
    ('https://bajkraj.hr', 'BajkRaj.hr'),
    ('https://bajkraj.cz', 'BajkRaj.cz'),
    ('https://bajkraj.si', 'BajkRaj.si'),
    ('https://bajkraj.sk', 'BajkRaj.sk'),
    ('https://olabike.gr', 'Olabike'),
    ('https://tudobike.pt', 'Tudobike'),
    ('https://bikerai.ro', 'BikeRai'),
    ('https://velosklad.bg', 'Velosklad'),
    ('https://visivelo.lv', 'Visivelo'),
    ('https://polkimet.fi', 'Polkimet'),
    ('https://fietsgear.nl', 'Fietsgear'),
)


class HagenWooNetwork(models.Model):
    _name = 'hagen.woo.network'
    _description = 'WordPress multisite network'
    _order = 'name'

    name = fields.Char(required=True)
    root_url = fields.Char(string='Network address', required=True, help='The site that hosts Network Admin, for example https://rattaproff.ee.')
    wp_username = fields.Char(string='WordPress username')
    application_password = fields.Char(string='Application password')
    company_id = fields.Many2one('res.company', required=True, default=lambda self: self.env.company)
    store_ids = fields.One2many(
        'hagen.woo.store',
        'network_id',
        string='Shops',
        context={'active_test': False},
    )
    last_discovery = fields.Text(readonly=True)

    def _auth(self):
        self.ensure_one()
        password = (self.application_password or '').replace(' ', '')
        if self.wp_username and password:
            return (self.wp_username, password)
        return None

    def action_discover_sites(self):
        for network in self:
            network._discover_sites()
        return True

    def action_pull_orders(self):
        stores = self.mapped('store_ids').filtered(lambda store: store.active and store._credentials_ok())
        if not stores:
            raise UserError(_('Activate a shop and add either its REST keys or the network application password.'))
        return stores.action_pull_orders()

    def _discover_sites(self):
        self.ensure_one()
        auth = self._auth()
        if not auth or not self.root_url:
            raise UserError(_('Set the WordPress username and application password on %s first.') % self.name)
        url = self.root_url.strip().rstrip('/') + '/xmlrpc.php'
        body = (
            '<?xml version="1.0"?>'
            '<methodCall><methodName>wp.getUsersBlogs</methodName><params>'
            f'<param><value><string>{escape(auth[0])}</string></value></param>'
            f'<param><value><string>{escape(auth[1])}</string></value></param>'
            '</params></methodCall>'
        )
        try:
            response = requests.post(url, data=body.encode(), headers={'Content-Type': 'text/xml'}, timeout=45)
        except requests.RequestException as error:
            raise UserError(_('Could not reach the network: %s') % error) from error
        if response.status_code >= 400:
            raise UserError(_('WordPress answered %s from %s.') % (response.status_code, url))
        blogs = self._parse_blogs(response.text)
        Store = self.env['hagen.woo.store'].with_context(active_test=False)
        created = 0
        for blog in blogs:
            site_url = (blog.get('url') or '').strip().rstrip('/')
            if not site_url:
                continue
            name = blog.get('blogName') or site_url
            store = Store.search([
                ('base_url', '=', site_url),
                ('company_id', '=', self.company_id.id),
            ], limit=1)
            vals = {
                'network_id': self.id,
                'blog_id': int(blog['blogid']) if str(blog.get('blogid') or '').isdigit() else False,
            }
            if store:
                store.write(vals)
            else:
                Store.create({
                    **vals,
                    'name': name,
                    'base_url': site_url,
                    'company_id': self.company_id.id,
                    'active': False,
                    'stock_sync': False,
                    'payment_journal_id': self._stripe_journal().id,
                })
                created += 1
        self.last_discovery = _('%s shops reported, %s new.') % (len(blogs), created)

    def _parse_blogs(self, xml_text):
        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError as error:
            raise UserError(_('WordPress did not return a site list.')) from error
        fault = root.find('.//faultString')
        if fault is not None and fault.text:
            raise UserError(fault.text)
        blogs = []
        for struct in root.findall('.//struct'):
            blog = {}
            for member in struct:
                key = member.findtext('name')
                value = member.find('value')
                if key and value is not None:
                    blog[key] = ''.join(value.itertext()).strip()
            if blog.get('url'):
                blogs.append(blog)
        if not blogs:
            raise UserError(_('WordPress returned no sites. XML-RPC may be disabled on this network.'))
        return blogs

    def _stripe_journal(self):
        return self.env['account.journal'].search([
            ('code', '=', 'STRP'),
            ('company_id', '=', self.company_id.id),
        ], limit=1)

    @api.model
    def seed_known_networks(self):
        company = self.env.company
        network = self.search([('root_url', '=', 'https://rattaproff.ee'), ('company_id', '=', company.id)], limit=1)
        if not network:
            network = self.create({
                'name': 'Rattaproff network',
                'root_url': 'https://rattaproff.ee',
                'company_id': company.id,
            })
        journal = network._stripe_journal()
        Store = self.env['hagen.woo.store'].with_context(active_test=False)
        for url, name in RATTAPROFF_SHOPS:
            store = Store.search([('base_url', '=', url), ('company_id', '=', company.id)], limit=1)
            if store:
                if not store.network_id:
                    store.network_id = network.id
                continue
            Store.create({
                'name': name,
                'base_url': url,
                'network_id': network.id,
                'company_id': company.id,
                'payment_journal_id': journal.id,
                'active': False,
                'stock_sync': False,
                'auto_confirm': True,
                'auto_invoice': True,
                'auto_pay': True,
                'payment_gateway': 'stripe,woocommerce_payments,wcpay',
            })
        self._ensure_ecb_rates()
        return True

    @api.model
    def _ensure_ecb_rates(self, codes=None):
        company = self.env.company
        if company.currency_id.name != 'HUF':
            return False
        try:
            response = requests.get(ECB_DAILY, timeout=30)
            response.raise_for_status()
            root = ET.fromstring(response.content)
        except (requests.RequestException, ET.ParseError) as error:
            _logger.warning('ECB rate download failed: %s', error)
            return False
        cube = root.find('.//e:Cube/e:Cube', ECB_NS)
        if cube is None:
            return False
        rate_date = cube.get('time')
        per_eur = {'EUR': 1.0}
        for node in cube:
            code = node.get('currency')
            value = node.get('rate')
            if code and value:
                per_eur[code] = float(value)
        huf_per_eur = per_eur.get('HUF')
        if not huf_per_eur:
            return False
        wanted = set(codes or ())
        if not wanted:
            wanted = {'EUR'}
        Rate = self.env['res.currency.rate']
        for code in wanted:
            foreign_per_eur = per_eur.get(code)
            if not foreign_per_eur:
                continue
            currency = self.env['res.currency'].with_context(active_test=False).search([('name', '=', code)], limit=1)
            if not currency:
                continue
            if not currency.active:
                currency.active = True
            if currency == company.currency_id:
                continue
            # Stored rate converts as 1 unit of this currency = (1 / rate) HUF.
            technical = foreign_per_eur / huf_per_eur
            existing = Rate.search([
                ('currency_id', '=', currency.id),
                ('name', '=', rate_date),
                ('company_id', 'in', [False, company.id]),
            ], limit=1)
            if existing:
                continue
            Rate.create({
                'currency_id': currency.id,
                'name': rate_date,
                'rate': technical,
                'company_id': company.id,
            })
        return True
