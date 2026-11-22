from odoo import models

from .product import hide_for_non_office


class StockPicking(models.Model):
    _inherit = 'stock.picking'

    def _get_view(self, view_id=None, view_type='form', **options):
        arch, view = super()._get_view(view_id, view_type, **options)
        return hide_for_non_office(arch, ('purchase_id', 'price_unit')), view
