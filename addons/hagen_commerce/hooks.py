import logging

_logger = logging.getLogger(__name__)

# Same shops as hagen.setup.STOCK_MASTER_SHOPS. blurbybike.hu has its own
# WooCommerce database and is a stock master, created switched off.
STOCK_MASTER_SHOPS = (
    ('Blurby store', 'https://blurbybike.com'),
    ('Blurby HU store', 'https://blurbybike.hu'),
    ('Hagen store', 'https://hagenbikes.com'),
)

COMPANY_DETAILS = (
    "<p>Hagen Group Kft.<br/>"
    "1053 Budapest, Kecskeméti utca 5.<br/>"
    "Cégjegyzékszám: 01-09-299788<br/>"
    "Adószám: 25979923-2-41<br/>"
    "Műhely: 1211 Budapest, Öntő utca 5.<br/>"
    "info@blurbybike.com</p>"
)


def post_init_hook(env):
    company = env.company
    company.write({
        'name': 'Hagen Group Kft.',
        'street': 'Kecskeméti utca 5.',
        'zip': '1053',
        'city': 'Budapest',
        'country_id': env.ref('base.hu').id,
        'email': 'info@blurbybike.com',
        'company_registry': '01-09-299788',
        'vat': '25979923-2-41',
        'company_details': COMPANY_DETAILS,
    })
    if 'l10n_hu_edi_server_mode' in company._fields:
        company.l10n_hu_edi_server_mode = 'demo'

    english = env['res.lang'].with_context(active_test=False).search([('code', '=', 'en_US')], limit=1)
    if english and not english.active:
        english.active = True

    drafts = env['account.move'].search([
        ('ref', '=', 'BLURBY-SAMPLE-DRAFT'),
        ('state', '=', 'draft'),
        ('company_id', '=', company.id),
    ])
    drafts.unlink()
    for partner in env['res.partner'].search([('name', '=', 'Sample customer (delete me)')]):
        if not env['account.move'].search_count([('partner_id', '=', partner.id)]):
            partner.unlink()

    workshop = env['res.partner'].search([
        ('name', 'in', ['Blurby workshop', 'Hagen Group workshop']),
        ('parent_id', '=', company.partner_id.id),
    ], limit=1)
    if workshop:
        workshop.name = 'Hagen Group workshop'

    goods = env['product.template'].search([
        '|',
        ('default_code', '=like', 'A%'),
        ('default_code', '=like', 'M-%'),
    ])
    if 'is_storable' in env['product.template']._fields:
        goods.write({'type': 'consu', 'is_storable': True})

    mto = env.ref('stock.route_warehouse0_mto', raise_if_not_found=False)
    if mto and not mto.active:
        mto.active = True

    journal = env['account.journal'].search([
        ('code', '=', 'STRP'),
        ('company_id', '=', company.id),
    ], limit=1)
    if not journal:
        journal = env['account.journal'].create({
            'name': 'Stripe Payments',
            'code': 'STRP',
            'type': 'bank',
            'company_id': company.id,
        })

    Store = env['hagen.woo.store'].with_context(active_test=False)
    for name, url in STOCK_MASTER_SHOPS:
        store = Store.search([('name', '=', name), ('company_id', '=', company.id)], limit=1)
        if not store:
            Store.create({
                'name': name,
                'base_url': url,
                'company_id': company.id,
                'payment_journal_id': journal.id,
                'active': False,
                'stock_sync': True,
            })
            continue
        values = {}
        if not store.base_url:
            values['base_url'] = url
        if not store.payment_journal_id:
            values['payment_journal_id'] = journal.id
        if not store.stock_sync and not store.active:
            values['stock_sync'] = True
        if values:
            store.write(values)
    _logger.info("Hagen Group commerce is ready for %s", company.name)
