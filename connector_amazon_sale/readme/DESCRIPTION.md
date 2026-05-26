Extends `connector_amazon` to import Amazon orders into Odoo.

On each poll cycle (default every 5 minutes):

1.  `GetOrders` fetches all orders updated since the last import cursor.
2.  One `queue_job` job per order calls `GetOrderItems` and
    `GetOrderAddress`.
3.  A `res.partner` is matched or created from the shipping address.
4.  A `sale.order` is created with lines mapped to internal products by
    Seller SKU (`product.product.default_code`).
5.  The `amz.order` staging record links the Amazon order to the Odoo
    sale order for traceability.

Products without a matching SKU are imported as description-only lines
so the order is never silently dropped.
