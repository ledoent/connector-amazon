from odoo import fields, models


class AmazonOrderLine(models.Model):
    _name = "amz.order.line"
    _description = "Amazon Order Line"

    amz_order_id = fields.Many2one(
        "amz.order",
        string="Amazon Order",
        required=True,
        ondelete="cascade",
        index=True,
    )
    backend_id = fields.Many2one(
        related="amz_order_id.backend_id",
        store=True,
        index=True,
    )
    order_item_id = fields.Char("Amazon Order Item ID", required=True, index=True)
    asin = fields.Char("ASIN")
    seller_sku = fields.Char("Seller SKU")
    title = fields.Char()
    quantity_ordered = fields.Integer("Qty Ordered")
    quantity_shipped = fields.Integer("Qty Shipped")
    item_price = fields.Monetary(currency_field="currency_id")
    item_tax = fields.Monetary("Tax", currency_field="currency_id")
    currency_id = fields.Many2one(
        related="amz_order_id.currency_id",
        store=True,
    )

    sale_order_line_id = fields.Many2one(
        "sale.order.line",
        ondelete="set null",
    )

    amz_order_line_unique = models.Constraint(
        "UNIQUE(amz_order_id, order_item_id)",
        "Amazon order item ID must be unique per order.",
    )
