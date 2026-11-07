import base64
import binascii
import csv
import io

from odoo import _, fields, models
from odoo.exceptions import UserError


class HagenBomImport(models.TransientModel):
    _name = 'hagen.bom.import'
    _description = 'Import bike kit or manufacture recipes'

    file = fields.Binary(required=True)
    filename = fields.Char()

    def action_import(self):
        self.ensure_one()
        if not self.file:
            raise UserError(_('Choose the recipe CSV first.'))
        payload = self.file
        if isinstance(payload, str):
            payload = payload.encode()
        try:
            decoded = base64.b64decode(payload, validate=True)
        except (ValueError, binascii.Error):
            decoded = payload
        rows = list(csv.DictReader(io.StringIO(decoded.decode('utf-8-sig'))))
        if not rows:
            raise UserError(_('The CSV has no data rows.'))
        confirmed = []
        for row in rows:
            status = (row.get('status') or '').strip().lower()
            bike = (row.get('bike_code') or '').strip()
            part = (row.get('part_code') or '').strip()
            if status != 'confirmed' or not bike or not part:
                continue
            try:
                qty = float(row.get('qty_per_bike') or 0)
            except ValueError as error:
                raise UserError(_('Quantity for %s / %s is not a number.') % (bike, part)) from error
            if qty <= 0:
                raise UserError(_('Quantity for %s / %s must be above zero.') % (bike, part))
            bom_type = (row.get('bom_type') or 'kit').strip().lower()
            if bom_type not in ('kit', 'manufacture'):
                raise UserError(_('bom_type for %s must be kit or manufacture.') % bike)
            confirmed.append((bike, part, qty, bom_type))
        if not confirmed:
            raise UserError(_('No rows are marked confirmed. needs_confirmation rows are left out on purpose.'))

        by_bike = {}
        for bike, part, qty, bom_type in confirmed:
            bucket = by_bike.setdefault(bike, {'type': bom_type, 'lines': []})
            if bucket['type'] != bom_type:
                raise UserError(_('Bike %s mixes kit and manufacture rows.') % bike)
            bucket['lines'].append((part, qty))

        company = self.env.company
        created = 0
        for bike_code, spec in by_bike.items():
            self._load_bike(company, bike_code, spec)
            created += 1
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Recipes loaded'),
                'message': _('%s bike recipes are active.') % created,
                'type': 'success',
                'sticky': False,
            },
        }

    def _load_bike(self, company, bike_code, spec):
        bike = self.env['product.product'].search([
            ('default_code', '=', bike_code),
            ('company_id', 'in', [False, company.id]),
        ], limit=1)
        if not bike:
            raise UserError(_('No product with internal reference %s.') % bike_code)
        lines = []
        for part_code, qty in spec['lines']:
            part = self.env['product.product'].search([
                ('default_code', '=', part_code),
                ('company_id', 'in', [False, company.id]),
            ], limit=1)
            if not part:
                raise UserError(_('No component with internal reference %s.') % part_code)
            lines.append((0, 0, {'product_id': part.id, 'product_qty': qty}))
        bom_type = 'phantom' if spec['type'] == 'kit' else 'normal'
        bom = self.env['mrp.bom'].search([
            ('product_tmpl_id', '=', bike.product_tmpl_id.id),
            ('company_id', 'in', [False, company.id]),
            ('type', 'in', ['phantom', 'normal']),
        ], limit=1)
        vals = {
            'product_tmpl_id': bike.product_tmpl_id.id,
            'product_id': bike.id,
            'product_qty': 1.0,
            'type': bom_type,
            'company_id': company.id,
            'bom_line_ids': [(5, 0, 0), *lines],
        }
        if bom:
            bom.write(vals)
        else:
            self.env['mrp.bom'].create(vals)
        self._set_routes(bike, spec['type'])

    def _set_routes(self, bike, bom_type):
        mto = self.env.ref('stock.route_warehouse0_mto', raise_if_not_found=False)
        manufacture = self.env.ref('mrp.route_warehouse0_manufacture', raise_if_not_found=False)
        template = bike.product_tmpl_id
        routes = template.route_ids
        if bom_type == 'manufacture':
            if mto:
                mto.active = True
                routes |= mto
            if manufacture:
                manufacture.active = True
                routes |= manufacture
        else:
            if mto:
                routes -= mto
            if manufacture:
                routes -= manufacture
        template.route_ids = routes
