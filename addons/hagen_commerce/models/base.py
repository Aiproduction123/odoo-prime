from odoo import models
from odoo.http import request


class Base(models.AbstractModel):
    _inherit = 'base'

    def get_base_url(self):
        """Use the address the browser actually opened.

        The laptop can use localhost and an office computer can use the
        office network address at the same time. Cron jobs have no browser,
        so they keep the stored fallback.
        """
        try:
            httprequest = request.httprequest
        except RuntimeError:
            httprequest = None
        if httprequest is not None and httprequest.host:
            return httprequest.url_root.rstrip('/')
        return super().get_base_url()
