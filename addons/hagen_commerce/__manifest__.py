{
    'name': 'Hagen Group commerce',
    'version': '19.0.1.1.0',
    'author': 'Hagen Group',
    'category': 'Sales',
    'summary': 'WooCommerce stores, Stripe payments, and bike kit recipes for Hagen Group Kft.',
    'depends': ['mrp', 'sale_management', 'stock', 'account', 'l10n_hu', 'l10n_hu_edi'],
    'data': [
        'security/ir.model.access.csv',
        'data/ir_cron.xml',
        'data/rattaproff_network.xml',
        'views/woo_network_views.xml',
        'views/woo_store_views.xml',
        'views/bom_import_views.xml',
    ],
    'post_init_hook': 'post_init_hook',
    'license': 'LGPL-3',
    'installable': True,
}
