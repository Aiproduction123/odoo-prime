from odoo import fields, models


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    hagen_woo_store_id = fields.Many2one('hagen.woo.store', string='WooCommerce store', copy=False, index=True)
    hagen_woo_order_id = fields.Char(string='WooCommerce order id', copy=False, index=True)
    hagen_woo_number = fields.Char(string='WooCommerce order number', copy=False)

    _woo_order_unique = models.Constraint(
        'UNIQUE(hagen_woo_store_id, hagen_woo_order_id)',
        'This WooCommerce order is already imported.',
    )
