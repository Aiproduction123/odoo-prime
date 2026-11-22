from odoo import api, fields, models

from .woo_store import OPENING_DONE_PARAM, OPENING_INVENTORY_REF


class StockInventoryAdjustmentName(models.TransientModel):
    _inherit = 'stock.inventory.adjustment.name'

    @api.model
    def _default_reference(self):
        if self.env['hagen.woo.store']._opening_inventory_applied():
            return 'Physical Inventory'
        return OPENING_INVENTORY_REF

    inventory_adjustment_name = fields.Char(default=_default_reference)

    def action_apply(self):
        result = super().action_apply()
        if any(OPENING_INVENTORY_REF.lower() in (wizard.inventory_adjustment_name or '').lower() for wizard in self):
            self.env['ir.config_parameter'].sudo().set_param(OPENING_DONE_PARAM, fields.Datetime.now())
        return result
