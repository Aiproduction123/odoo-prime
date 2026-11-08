from odoo import models
from odoo.http import request


class IrHttp(models.AbstractModel):
    _inherit = 'ir.http'

    def session_info(self):
        info = super().session_info()
        info['web.base.url'] = request.httprequest.url_root.rstrip('/')
        return info
