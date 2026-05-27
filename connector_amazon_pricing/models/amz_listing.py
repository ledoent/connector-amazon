import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class AmazonListing(models.Model):
    _name = "amz.listing"
    _description = "Amazon Product Listing"
    _rec_name = "seller_sku"
    _order = "seller_sku"

    backend_id = fields.Many2one(
        "amz.backend",
        required=True,
        index=True,
        ondelete="cascade",
    )
    product_id = fields.Many2one(
        "product.product",
        required=True,
        index=True,
        ondelete="restrict",
    )
    seller_sku = fields.Char(required=True, index=True)
    asin = fields.Char(index=True)
    active = fields.Boolean(default=True)

    currency_id = fields.Many2one(
        "res.currency",
        related="backend_id.company_id.currency_id",
        store=True,
    )
    current_list_price = fields.Monetary()
    buy_box_price = fields.Monetary()
    buy_box_winner = fields.Selection(
        [("us", "Us"), ("competitor", "Competitor")],
        string="Buy Box Winner",
    )
    computed_target_price = fields.Monetary()
    last_price_pull_date = fields.Datetime(readonly=True)
    last_price_push_date = fields.Datetime(readonly=True)

    _amz_listing_backend_sku_unique = models.Constraint(
        "UNIQUE(backend_id, seller_sku)",
        "Amazon SKU must be unique per backend.",
    )

    @api.model
    def _upsert(self, backend, product, sku, asin=None):
        """Create or update an amz.listing for this backend/SKU pair."""
        existing = self.search(
            [("backend_id", "=", backend.id), ("seller_sku", "=", sku)],
            limit=1,
        )
        if existing:
            vals = {}
            if asin and existing.asin != asin:
                vals["asin"] = asin
            if existing.product_id.id != product.id:
                vals["product_id"] = product.id
            if vals:
                existing.write(vals)
            return existing
        return self.create(
            {
                "backend_id": backend.id,
                "product_id": product.id,
                "seller_sku": sku,
                "asin": asin,
            }
        )
