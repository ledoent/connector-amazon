Connects Odoo to the Amazon Selling Partner API (SP-API) using OAuth2
Login with Amazon (LWA) credentials.

This base module provides:

- ``amz.backend`` — LWA credential storage, marketplace selection, and sandbox toggle.
- ``amz.order`` / ``amz.order.line`` — staging models that mirror Amazon order data before mapping to ``sale.order``.
- A disabled cron template that polls ``GetOrders`` every 5 minutes.

Companion modules:

- ``connector_amazon_sale`` — imports Amazon orders into ``sale.order``.
- ``connector_amazon_stock`` — pushes carrier tracking numbers to Amazon via ``ConfirmShipment``.
