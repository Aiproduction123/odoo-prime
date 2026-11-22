import base64
import binascii
import csv
import io

from odoo import _, fields, models
from odoo.exceptions import UserError

DRAFT_REFERENCE = 'Draft for sign-off'
LIVE_REFERENCE = 'Confirmed recipe'


class HagenBomImport(models.TransientModel):
    _name = 'hagen.bom.import'
    _description = 'Import bike kit or manufacture recipes'

    file = fields.Binary(required=True)
    filename = fields.Char()

    def _rows(self):
        payload = self.file
        if isinstance(payload, str):
            payload = payload.encode()
        try:
            decoded = base64.b64decode(payload, validate=True)
        except (ValueError, binascii.Error):
            decoded = payload
        return list(csv.DictReader(io.StringIO(decoded.decode('utf-8-sig'))))

    def action_import(self):
        self.ensure_one()
        if not self.file:
            raise UserError(_('Choose the recipe CSV first.'))
        rows = self._rows()
        if not rows:
            raise UserError(_('The CSV has no data rows.'))

        # confirmed rows build the live recipe; confirmed + inferred rows build the draft
        live, draft = {}, {}
        for number, row in enumerate(rows, start=2):
            status = (row.get('status') or '').strip().lower()
            if status not in ('confirmed', 'inferred'):
                continue
            bike = (row.get('bike_code') or '').strip()
            part = (row.get('part_code') or '').strip()
            if not bike or not part:
                raise UserError(_('Line %s is marked %s but has no bike or part code.') % (number, status))
            try:
                qty = float(row.get('qty_per_bike') or 0)
            except ValueError as error:
                raise UserError(_('Quantity for %s / %s is not a number.') % (bike, part)) from error
            if qty <= 0:
                raise UserError(_('Quantity for %s / %s must be above zero.') % (bike, part))
            bom_type = (row.get('bom_type') or 'kit').strip().lower()
            if bom_type not in ('kit', 'manufacture'):
                raise UserError(_('bom_type for %s must be kit or manufacture.') % bike)
            targets = (live, draft) if status == 'confirmed' else (draft,)
            for target in targets:
                bucket = target.setdefault(bike, {'type': bom_type, 'lines': {}, 'inferred': False})
                if bucket['type'] != bom_type:
                    raise UserError(_('Bike %s mixes kit and manufacture rows.') % bike)
                bucket['lines'][part] = bucket['lines'].get(part, 0.0) + qty
                if status == 'inferred':
                    bucket['inferred'] = True
        if not live and not draft:
            raise UserError(_('No rows are marked confirmed or inferred. needs_confirmation rows are left out on purpose.'))

        company = self.env.company
        for bike_code, spec in live.items():
            self._load_bike(company, bike_code, spec, live=True)
        drafts = 0
        for bike_code, spec in draft.items():
            if spec['inferred']:
                self._load_bike(company, bike_code, spec, live=False)
                drafts += 1
            else:
                self._drop_draft(company, bike_code)
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Recipes loaded'),
                'message': _('%(live)s recipes are live. %(drafts)s draft recipes wait for sign-off '
                             '(Bills of Materials → Filters → Archived).') % {'live': len(live), 'drafts': drafts},
                'type': 'success',
                'sticky': False,
            },
        }

    def _product(self, company, code, label):
        product = self.env['product.product'].with_context(active_test=False).search([
            ('default_code', '=', code),
            ('company_id', 'in', [False, company.id]),
        ], limit=1)
        if not product:
            raise UserError(_('No %s with internal reference %s.') % (label, code))
        return product

    def _find_bom(self, company, bike, live):
        domain = [
            ('product_tmpl_id', '=', bike.product_tmpl_id.id),
            ('company_id', 'in', [False, company.id]),
        ]
        if live:
            domain += [('active', '=', True), ('code', '!=', DRAFT_REFERENCE)]
        else:
            domain += [('code', '=', DRAFT_REFERENCE)]
        return self.env['mrp.bom'].with_context(active_test=False).search(domain, limit=1)

    def _drop_draft(self, company, bike_code):
        bike = self.env['product.product'].search([('default_code', '=', bike_code)], limit=1)
        if bike:
            self._find_bom(company, bike, live=False).unlink()

    def _load_bike(self, company, bike_code, spec, live):
        bike = self._product(company, bike_code, _('bike or frameset'))
        lines = [
            (0, 0, {'product_id': self._product(company, part_code, _('component')).id, 'product_qty': qty})
            for part_code, qty in spec['lines'].items()
        ]
        vals = {
            'product_tmpl_id': bike.product_tmpl_id.id,
            'product_id': bike.id,
            'product_qty': 1.0,
            'type': 'phantom' if spec['type'] == 'kit' else 'normal',
            'company_id': company.id,
            'code': LIVE_REFERENCE if live else DRAFT_REFERENCE,
            'active': live,
            'bom_line_ids': [(5, 0, 0), *lines],
        }
        bom = self._find_bom(company, bike, live)
        if bom:
            bom.write(vals)
        else:
            self.env['mrp.bom'].create(vals)
        if live:
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
