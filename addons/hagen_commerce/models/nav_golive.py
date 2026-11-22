from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

SEATS = {
    '25979923-2-41': {'street': 'Kecskeméti utca 5.', 'zip': '1053', 'city': 'Budapest'},
    '25979923-2-43': {'street': 'Öntő utca 5.', 'zip': '1211', 'city': 'Budapest'},
}
CREDENTIALS = (
    ('l10n_hu_edi_username', 'technikai felhasználónév'),
    ('l10n_hu_edi_password', 'jelszó'),
    ('l10n_hu_edi_signature_key', 'XML aláírókulcs'),
    ('l10n_hu_edi_replacement_key', 'XML cserekulcs'),
)


class ResCompany(models.Model):
    _inherit = 'res.company'

    hagen_nav_extract_confirmed = fields.Boolean(
        string='Company extract (cégkivonat) checked',
        groups='base.group_system',
        copy=False,
    )

    @api.constrains('l10n_hu_edi_server_mode')
    def _check_hagen_nav_extract(self):
        for company in self:
            if company.l10n_hu_edi_server_mode in ('test', 'production') and not company.sudo().hagen_nav_extract_confirmed:
                raise ValidationError(_(
                    'NAV stays in Demo until the company extract (cégkivonat) is confirmed. '
                    'Use Invoicing → Configuration → NAV go-live.'
                ))


class HagenNavGolive(models.TransientModel):
    _name = 'hagen.nav.golive'
    _description = 'Switch NAV e-invoicing from Demo to live'

    company_id = fields.Many2one('res.company', default=lambda self: self.env.company, required=True)
    current_vat = fields.Char(related='company_id.vat', string='Tax number now')
    current_mode = fields.Selection(related='company_id.l10n_hu_edi_server_mode', string='NAV mode now')
    tax_number = fields.Selection([
        ('25979923-2-41', '25979923-2-41 (seat 1053 Budapest, Kecskeméti utca 5.)'),
        ('25979923-2-43', '25979923-2-43 (seat 1211 Budapest, Öntő utca 5.)'),
    ], string='Tax number on the company extract', required=True)
    extract_confirmed = fields.Boolean(string='I checked the latest company extract (cégkivonat): it shows this tax number and seat')
    mode = fields.Selection([
        ('test', 'Test (NAV test system, needs a test-portal user)'),
        ('production', 'Production (live invoices are reported to NAV)'),
    ], required=True, default='production')
    l10n_hu_edi_username = fields.Char(string='Technical username (technikai felhasználónév)')
    l10n_hu_edi_password = fields.Char(string='Password (jelszó)')
    l10n_hu_edi_signature_key = fields.Char(string='XML signing key (XML aláírókulcs)')
    l10n_hu_edi_replacement_key = fields.Char(string='XML exchange key (XML cserekulcs)')

    def action_switch(self):
        self.ensure_one()
        if not self.extract_confirmed:
            raise UserError(_('Tick the company extract confirmation first. NAV stays in Demo.'))
        company = self.company_id.sudo()
        values = {field: self[field] for field, _label in CREDENTIALS if self[field]}
        missing = [label for field, label in CREDENTIALS if not values.get(field) and not company[field]]
        if missing:
            raise UserError(_('Still missing: %s. NAV stays in Demo.') % ', '.join(missing))
        company.write({
            **values,
            **SEATS[self.tax_number],
            'vat': self.tax_number,
            'country_id': self.env.ref('base.hu').id,
            'hagen_nav_extract_confirmed': True,
            'l10n_hu_edi_server_mode': self.mode,
        })
        # Any failure here rolls the whole switch back to Demo.
        try:
            company._l10n_hu_edi_test_credentials()
        except UserError:
            raise
        except Exception as error:  # noqa: BLE001 - Odoo's parser crashes on NAV's rejection answer
            raise UserError(_(
                'NAV rejected these credentials for %(vat)s in %(mode)s mode. NAV stays in Demo. '
                'Check that the technical user belongs to this tax number, and that Test mode uses a '
                'test-portal user. Details: %(error)s'
            ) % {'vat': self.tax_number, 'mode': self.mode, 'error': error}) from error
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('NAV is live'),
                'message': _('NAV accepted the credentials for %(vat)s. Mode: %(mode)s.') % {
                    'vat': self.tax_number, 'mode': self.mode,
                },
                'type': 'success',
                'sticky': True,
                'next': {'type': 'ir.actions.act_window_close'},
            },
        }
