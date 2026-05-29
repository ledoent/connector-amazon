from odoo import fields, models


class AmazonPriceHistory(models.Model):
    _name = "amz.price.history"
    _description = "Amazon Price Push History"
    _order = "date desc, id desc"

    listing_id = fields.Many2one(
        "amz.listing",
        required=True,
        index=True,
        ondelete="cascade",
    )
    backend_id = fields.Many2one(
        related="listing_id.backend_id", store=True, index=True
    )
    product_id = fields.Many2one(related="listing_id.product_id", store=True)
    seller_sku = fields.Char(related="listing_id.seller_sku", store=True)
    old_price = fields.Monetary(currency_field="currency_id")
    new_price = fields.Monetary(currency_field="currency_id")
    pricing_rule = fields.Char()
    trigger = fields.Selection(
        [
            ("manual", "Manual"),
            ("cron", "Scheduled"),
            ("notification", "Offer Notification"),
        ],
        default="manual",
        index=True,
    )
    date = fields.Datetime(default=fields.Datetime.now, index=True)
    user_id = fields.Many2one("res.users", default=lambda self: self.env.user)
    currency_id = fields.Many2one(related="listing_id.currency_id")
