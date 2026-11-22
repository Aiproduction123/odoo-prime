import logging
import xml.etree.ElementTree as ET
from xml.sax.saxutils import escape

import requests

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from .woo_http import request as woo_request

_logger = logging.getLogger(__name__)

ECB_DAILY = 'https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml'
ECB_NS = {'gesmes': 'http://www.gesmes.org/xml/2002-08-01', 'e': 'http://www.ecb.int/vocabulary/2002-08-01/eurofxref'}

# Active shops on the rattaproff.ee WordPress multisite, in blog id order.
# Blog 2 is not an active shop. Each site has its own WooCommerce orders and
# VAT. One WordPress application password on the network authenticates every
# site's /wp-json/wc/v3/ (HTTP Basic). The network admin lives on rattaproff.ee.
RATTAPROFF_SHOPS = (
    ('https://rattaproff.ee', 'Rattaproff'),
    ('https://velochic.fr', 'Velochic'),
    ('https://fahrrad7.de', 'Fahrrad 7'),
    ('https://bicirey.es', 'Bicirey'),
    ('https://bicinegozio.it', 'Bicinegozio'),
    ('https://fietsgear.nl', 'Fietsgear'),
    ('https://polkimet.fi', 'Polkimet'),
    ('https://rowerkrol.pl', 'Rowerkról.pl'),
    ('https://velocentras.lt', 'Velocentras'),
    ('https://visivelo.lv', 'Visivelo'),
    ('https://bajkraj.sk', 'BajkRaj.sk'),
    ('https://bajkraj.si', 'BajkRaj.si'),
    ('https://bajkraj.cz', 'BajkRaj.cz'),
    ('https://bajkraj.hr', 'BajkRaj.hr'),
    ('https://cykelpoint.dk', 'Cykelpoint.dk'),
    ('https://velosklad.bg', 'Velosklad'),
    ('https://cykelpoint.se', 'Cykelpoint.se'),
    ('https://bikerai.ro', 'BikeRai'),
    ('https://tudobike.pt', 'Tudobike'),
    ('https://olabike.gr', 'Olabike'),
)
RATTAPROFF_BLOG_IDS = {
    'https://rattaproff.ee': 1,
    'https://velochic.fr': 3,
    'https://fahrrad7.de': 4,
    'https://bicirey.es': 5,
    'https://bicinegozio.it': 6,
    'https://fietsgear.nl': 7,
    'https://polkimet.fi': 8,
    'https://rowerkrol.pl': 9,
    'https://velocentras.lt': 10,
    'https://visivelo.lv': 11,
    'https://bajkraj.sk': 12,
    'https://bajkraj.si': 13,
    'https://bajkraj.cz': 14,
    'https://bajkraj.hr': 15,
    'https://cykelpoint.dk': 16,
    'https://velosklad.bg': 17,
    'https://cykelpoint.se': 18,
    'https://bikerai.ro': 19,
    'https://tudobike.pt': 20,
    'https://olabike.gr': 21,
}
if len(RATTAPROFF_SHOPS) != 20 or set(RATTAPROFF_BLOG_IDS) != {url for url, _name in RATTAPROFF_SHOPS}:
    raise RuntimeError('RATTAPROFF_SHOPS and RATTAPROFF_BLOG_IDS are out of sync')


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
    last_discovery = fields.Text(string='Last check', readonly=True)

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

    def _connection_notice(self, message, warning):
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Connection test'),
                'message': message,
                'type': 'warning' if warning else 'success',
                'sticky': warning,
            },
        }

    def action_test_connection(self):
        """Read one order from every shop with the network password. Imports and posts nothing.

        A bad password or a shop that does not answer is reported on the form.
        The button does not raise, so a failed test is not a traceback.
        """
        self.ensure_one()
        if not self._auth():
            message = _('Set the WordPress username and application password on %s first.') % self.name
            self.last_discovery = message
            return self._connection_notice(message, warning=True)
        lines = []
        for store in self.store_ids.with_context(active_test=False).filtered('base_url'):
            try:
                store._woo_request('GET', 'orders', params={'per_page': 1})
                lines.append(_('%s: connected') % store.name)
            except UserError as error:
                lines.append(_('%s: %s') % (store.name, str(error)[:160]))
            except Exception as error:
                _logger.exception('Connection test failed for %s', store.name)
                lines.append(_('%s: %s') % (store.name, str(error)[:160]))
        self.last_discovery = '\n'.join(lines)
        ok = sum(1 for line in lines if line.endswith(_('connected')))
        return self._connection_notice(
            _('%(ok)s of %(total)s shops answered. Details are under Last check.') % {'ok': ok, 'total': len(lines)},
            warning=ok != len(lines),
        )

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
            response = woo_request(
                'POST', url, data=body.encode(), headers={'Content-Type': 'text/xml'}, timeout=45,
            )
        except requests.RequestException as error:
            raise UserError(_('Could not reach the network: %s') % error) from error
        if response.status_code in (403, 405) or (response.status_code < 400 and 'methodResponse' not in response.text):
            raise UserError(_(
                '%(site)s blocks XML-RPC (HTTP %(code)s), so the site list cannot be read automatically. '
                'The shops listed below are already set up; add a new shop with New on WooCommerce stores, '
                'or allow /xmlrpc.php for the Odoo server in the hosting firewall.'
            ) % {'site': self.root_url, 'code': response.status_code})
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
            blog_id = RATTAPROFF_BLOG_IDS[url]
            store = Store.search([('base_url', '=', url), ('company_id', '=', company.id)], limit=1)
            if store:
                values = {}
                if not store.network_id:
                    values['network_id'] = network.id
                if store.blog_id != blog_id:
                    values['blog_id'] = blog_id
                if values:
                    store.write(values)
                continue
            Store.create({
                'name': name,
                'base_url': url,
                'blog_id': blog_id,
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
