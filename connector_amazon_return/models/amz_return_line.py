from odoo import fields, models


class AmazonReturnLine(models.Model):
    _name = "amz.return.line"
    _description = "Amazon Return Line"

    return_id = fields.Many2one(
        "amz.return",
        required=True,
        index=True,
        ondelete="cascade",
    )
    order_item_id = fields.Char("Order Item ID", index=True)
    amz_order_line_id = fields.Many2one(
        "amz.order.line", "Amazon Order Line", ondelete="set null"
    )
    product_id = fields.Many2one("product.product", "Product")
    seller_sku = fields.Char("Seller SKU")
    asin = fields.Char("ASIN")
    quantity = fields.Float(default=1.0)
    return_reason = fields.Char()
