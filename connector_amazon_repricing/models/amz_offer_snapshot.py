from odoo import fields, models


class AmazonOfferSnapshot(models.Model):
    _name = "amz.offer.snapshot"
    _description = "Amazon Competitor Offer Snapshot"
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
    asin = fields.Char(related="listing_id.asin", store=True)
    seller_id = fields.Char("Seller ID", index=True)
    is_own_offer = fields.Boolean("Our Offer")
    is_buy_box_winner = fields.Boolean("Buy Box Winner")
    price = fields.Monetary(currency_field="currency_id")
    date = fields.Datetime(default=fields.Datetime.now, index=True)
    currency_id = fields.Many2one(related="listing_id.currency_id")
