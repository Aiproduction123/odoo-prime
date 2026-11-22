import math

from odoo import api, fields, models

# Odoo 19 checks field groups even inside its own code, so costs are hidden
# on the screens instead; a field-level group would stop employees validating receipts.
OFFICE_ONLY = 'hagen_commerce.group_office,stock.group_stock_manager,purchase.group_purchase_user,account.group_account_invoice'
COST_FIELDS = ('standard_price', 'seller_ids', 'variant_seller_ids', 'standard_price_uom', 'purchase_ok')


def hide_for_non_office(arch, names):
    for node in arch.iter():
        if node.get('name') in names or node.get('for') in names:
            node.set('groups', OFFICE_ONLY)
    return arch


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    def _get_view(self, view_id=None, view_type='form', **options):
        arch, view = super()._get_view(view_id, view_type, **options)
        return hide_for_non_office(arch, COST_FIELDS), view

    hagen_sellable_qty = fields.Integer(
        string='Sellable on webshops',
        compute='_compute_hagen_sellable_qty',
        help='What the stock-master WooCommerce shops are told: finished units in stock '
             'plus what can still be built from free parts. Kits and the complete bikes '
             'that share a part draw from the same parts.',
    )

    @api.depends_context('warehouse_id')
    def _compute_hagen_sellable_qty(self):
        warehouse = self.env['stock.warehouse'].search([('company_id', '=', self.env.company.id)], limit=1)
        for template in self:
            variant = template.product_variant_id
            template.hagen_sellable_qty = variant._hagen_sellable_qty(warehouse) if variant else 0


class ProductProduct(models.Model):
    _inherit = 'product.product'

    def _get_view(self, view_id=None, view_type='form', **options):
        arch, view = super()._get_view(view_id, view_type, **options)
        return hide_for_non_office(arch, COST_FIELDS), view

    def _hagen_free_units(self, warehouse):
        """Units on the shelf that no confirmed order or build has claimed yet."""
        self.ensure_one()
        if not self.is_storable:
            return 0.0
        product = self.with_context(warehouse_id=warehouse.id)
        unclaimed = product.qty_available - product.outgoing_qty
        return max(0.0, min(product.free_qty, unclaimed))

    def _hagen_needs(self, bom):
        """Component → quantity needed for one unit of the BoM's product."""
        needs = {}
        for line in bom.bom_line_ids:
            component = line.product_id
            need = line.product_uom_id._compute_quantity(line.product_qty, component.uom_id) / (bom.product_qty or 1.0)
            if need > 0:
                needs[component] = needs.get(component, 0.0) + need
        return needs

    def _hagen_apply_spec(self, needs, spec):
        """Swap, drop and add parts the way the webshop options change the build."""
        Product = self.env['product.product']
        by_code = {product.default_code: product for product in needs}

        def find(code):
            return by_code.get(code) or Product.search([('default_code', '=', code)], limit=1)

        needs = dict(needs)
        for old, new in spec.get('replace', []):
            product = by_code.get(old)
            if product in needs:
                qty = needs.pop(product)
                target = find(new)
                if target:
                    needs[target] = needs.get(target, 0.0) + qty
                    by_code[new] = target
        for code in spec.get('remove', []):
            product = by_code.get(code)
            if product in needs:
                needs.pop(product)
        for code, qty, _label in spec.get('add', []):
            target = find(code)
            if target:
                needs[target] = needs.get(target, 0.0) + qty
                by_code[code] = target
        return needs

    def _hagen_buildable(self, needs, warehouse, depth=0):
        limits = []
        for component, need in needs.items():
            if not component.is_storable and not self._hagen_find_bom(component, 'phantom'):
                continue
            limits.append(component._hagen_sellable_qty(warehouse, depth + 1) / need)
        return min(limits) if limits else 0.0

    def _hagen_find_bom(self, product, bom_type=None):
        boms = self.env['mrp.bom'].sudo()._bom_find(product, company_id=self.env.company.id, bom_type=bom_type)
        return boms.get(product) or self.env['mrp.bom']

    def _hagen_sellable_qty(self, warehouse, depth=0, spec=None):
        """Sellable units. With a webshop build spec, only what can be built in that configuration."""
        self.ensure_one()
        if depth > 5:
            return 0
        bom = self._hagen_find_bom(self)
        changed = bool(spec and (spec.get('replace') or spec.get('remove') or spec.get('add')))
        if bom and changed:
            qty = self._hagen_buildable(self._hagen_apply_spec(self._hagen_needs(bom), spec), warehouse, depth)
        elif bom and bom.type == 'phantom':
            qty = self._hagen_buildable(self._hagen_needs(bom), warehouse, depth)
        else:
            qty = self._hagen_free_units(warehouse)
            if bom:
                qty += self._hagen_buildable(self._hagen_needs(bom), warehouse, depth)
        return int(math.floor(max(qty, 0.0) + 1e-6))
