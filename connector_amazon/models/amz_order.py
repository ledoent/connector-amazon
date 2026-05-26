from odoo import fields, models

AMZ_ORDER_STATUS = [
    ("PendingAvailability", "Pending Availability"),
    ("Pending", "Pending"),
    ("Unshipped", "Unshipped"),
    ("PartiallyShipped", "Partially Shipped"),
    ("Shipped", "Shipped"),
    ("InvoiceUnconfirmed", "Invoice Unconfirmed"),
    ("Canceled", "Canceled"),
    ("Unfulfillable", "Unfulfillable"),
]


class AmazonOrder(models.Model):
    _name = "amz.order"
    _description = "Amazon Order"
    _order = "purchase_date desc"

    backend_id = fields.Many2one(
        "amz.backend",
        string="Backend",
        required=True,
        ondelete="restrict",
        index=True,
    )
    amz_order_id = fields.Char(
        "Amazon Order ID",
        required=True,
        index=True,
    )
    amazon_status = fields.Selection(AMZ_ORDER_STATUS)
    fulfillment_channel = fields.Selection(
        [("MFN", "Merchant (MFN)"), ("AFN", "Amazon (FBA)")],
        string="Fulfillment",
    )
    marketplace_id = fields.Char("Marketplace ID")
    purchase_date = fields.Datetime()
    last_update_date = fields.Datetime("Last Updated")
    sync_date = fields.Datetime("Last Synced", readonly=True)

    order_total = fields.Monetary(currency_field="currency_id")
    currency_id = fields.Many2one(
        "res.currency",
        default=lambda self: self.env.ref("base.USD"),
    )

    sale_order_id = fields.Many2one(
        "sale.order",
        ondelete="set null",
        index=True,
    )

    amz_order_line_ids = fields.One2many(
        "amz.order.line",
        "amz_order_id",
    )

    _sql_constraints = [
        (
            "amz_order_backend_unique",
            "UNIQUE(backend_id, amz_order_id)",
            "Amazon order ID must be unique per backend.",
        ),
    ]
