Extends ``connector_amazon`` to import Amazon orders into Odoo.

On each poll cycle (default every 5 minutes):

1. ``GetOrders`` fetches all orders updated since the last import cursor.
2. One ``queue_job`` job per order calls ``GetOrderItems`` and ``GetOrderAddress``.
3. A ``res.partner`` is matched or created from the shipping address.
4. A ``sale.order`` is created with lines mapped to internal products by Seller SKU (``product.product.default_code``).
5. The ``amz.order`` staging record links the Amazon order to the Odoo sale order for traceability.

Products without a matching SKU are imported as description-only lines so the order is never silently dropped.

Enable **Auto-Invoice Orders** on the backend to confirm each imported order and
create + post a customer invoice automatically — useful for settlement-to-invoice
reconciliation (see the Settlements connector). For this to produce an invoice,
the order's products must be invoiceable on order (``invoice_policy='order'`` is
recommended); otherwise the step logs "nothing to invoice" and skips.
