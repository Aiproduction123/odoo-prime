from markupsafe import Markup

from odoo import api, fields, models


class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    hagen_build_spec = fields.Json(string='Webshop build changes', copy=False)
    hagen_build_notes = fields.Text(string='Webshop build options', copy=False)


class MrpProduction(models.Model):
    _inherit = 'mrp.production'

    hagen_build_notes = fields.Text(string='Webshop build options', copy=False, readonly=True)

    @api.model_create_multi
    def create(self, vals_list):
        productions = super().create(vals_list)
        for production in productions:
            line = production.sale_line_id
            if line and (line.hagen_build_spec or line.hagen_build_notes):
                production._hagen_apply_build(line.hagen_build_spec or {}, line.hagen_build_notes or '')
        return productions

    def _hagen_apply_build(self, spec, notes):
        """Turn the base recipe into the bike the customer configured, before anything is reserved."""
        self.ensure_one()
        Product = self.env['product.product']
        warnings = []
        if self.state == 'draft':
            moves = self.move_raw_ids

            def move_for(code):
                return moves.filtered(lambda move: move.product_id.default_code == code and move.state == 'draft')[:1]

            for old, new in spec.get('replace', []):
                move = move_for(old)
                target = Product.search([('default_code', '=', new)], limit=1)
                if not move:
                    continue
                if not target:
                    warnings.append(f'Part {new} does not exist in Odoo: {old} was left in.')
                else:
                    move.write({'product_id': target.id, 'product_uom': target.uom_id.id, 'bom_line_id': False})
            for code in spec.get('remove', []):
                move = move_for(code)
                if move:
                    moves -= move
                    move.unlink()
            additions = []
            for code, qty, _label in spec.get('add', []):
                target = Product.search([('default_code', '=', code)], limit=1)
                if not target:
                    warnings.append(f'Part {code} does not exist in Odoo: add it by hand.')
                    continue
                additions.append(self._get_move_raw_values(target, qty * self.product_qty, target.uom_id))
            if additions:
                self.env['stock.move'].create(additions)
        elif spec:
            warnings.append('The order was already confirmed: swap the parts on this MO by hand.')
        text = notes + ''.join(f'\nCHECK: {warning}' for warning in warnings)
        self.hagen_build_notes = text
        if text:
            self.message_post(body=Markup('<br/>').join(text.split('\n')))


class StockRule(models.Model):
    _inherit = 'stock.rule'

    def _make_mo_get_domain(self, procurement, bom):
        domain = super()._make_mo_get_domain(procurement, bom)
        line_id = procurement.values.get('sale_line_id')
        if line_id:
            line = self.env['sale.order.line'].browse(line_id)
            if line.exists() and (line.hagen_build_spec or line.hagen_build_notes):
                # A configured bike gets its own MO, never merged with another order line.
                domain += (('sale_line_id', '=', line.id),)
        return domain
