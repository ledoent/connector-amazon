Extends `connector_amazon_sale` to push shipment tracking numbers back
to Amazon via the SP-API `ConfirmShipment` endpoint.

When a delivery order (`stock.picking`) is validated:

1.  The picking is checked for a carrier tracking reference and a linked
    Amazon order (via the associated `sale.order`).
2.  If both are present, a `queue_job` job is enqueued to call
    `ConfirmShipment` with the carrier code, tracking number, and
    shipped item quantities.
3.  Odoo carrier names are mapped to Amazon carrier codes (UPS, USPS,
    FedEx, DHL, etc.); unknown carriers fall back to `"Other"`.

If the SP-API call fails, the error is logged and the `queue_job` job is
left in a failed state under **Settings > Technical > Queue Jobs**, where it
can be inspected and retried.
