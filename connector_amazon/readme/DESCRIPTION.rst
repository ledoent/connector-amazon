Connects Odoo to the Amazon Selling Partner API (SP-API) using OAuth2
Login with Amazon (LWA) credentials.

This base module provides:

* ``amz.backend`` — credential storage (LWA client ID/secret/refresh token),
  marketplace selection, and sandbox mode toggle.
* ``amz.order`` / ``amz.order.line`` — staging models that mirror Amazon order
  data before it is mapped to ``sale.order``.
* A disabled cron template that polls ``GetOrders`` on a 5-minute schedule.

Companion modules:

* ``connector_amazon_sale`` — imports Amazon orders into ``sale.order``.
* ``connector_amazon_stock`` — pushes carrier tracking numbers back to Amazon
  via ``ConfirmShipment``.
