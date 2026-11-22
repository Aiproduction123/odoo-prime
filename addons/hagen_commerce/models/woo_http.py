"""HTTP calls to WooCommerce and WordPress.

Cloudflare rejects the default python-requests User-Agent with HTTP 403.
Every shop request sends the agent below, which was checked against the stores.
"""

import requests

USER_AGENT = 'Odoo hagen_commerce/1.0'


def request(method, url, **kwargs):
    headers = {'User-Agent': USER_AGENT}
    extra = kwargs.pop('headers', None)
    if extra:
        headers.update(extra)
    kwargs['headers'] = headers
    return requests.request(method, url, **kwargs)
