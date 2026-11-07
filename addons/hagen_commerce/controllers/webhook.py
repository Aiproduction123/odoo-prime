import hmac
import logging

from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)


class HagenWooWebhook(http.Controller):
    @http.route(
        '/hagen/woo/<int:store_id>/<string:token>',
        type='http',
        auth='public',
        methods=['POST'],
        csrf=False,
    )
    def woo_order(self, store_id, token):
        store = request.env['hagen.woo.store'].sudo().browse(store_id).exists()
        if not store or not store.webhook_token or not hmac.compare_digest(store.webhook_token, token):
            return request.make_json_response({'error': 'unauthorized'}, status=401)
        payload = request.httprequest.get_json(silent=True) or {}
        try:
            with request.env.cr.savepoint():
                store._import_paid_order(payload)
        except Exception:
            _logger.exception("WooCommerce webhook failed for store %s", store.id)
            return request.make_json_response({'error': 'import failed'}, status=400)
        return request.make_json_response({'ok': True})
