import logging

from odoo import fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class AmazonBackend(models.Model):
    _inherit = "amz.backend"

    seller_id = fields.Char(
        "Amazon Seller ID",
        help="Merchant Token from Seller Central > Account Info > Merchant Token.",
    )
    pricing_mode = fields.Selection(
        [
            ("pricelist", "Odoo Pricelist"),
            ("competitive", "Amazon Competitive Floor"),
            ("manual", "Manual / No Sync"),
        ],
        default="pricelist",
    )
    competitive_rule = fields.Selection(
        [
            ("match_buy_box", "Match Buy Box"),
            ("undercut_buy_box", "Undercut Buy Box by %"),
            ("floor_cost_plus", "Floor: Cost + Margin %"),
        ],
        default="match_buy_box",
    )
    competitive_undercut_pct = fields.Float(
        "Undercut %",
        default=1.0,
        help="Percentage below buy box price (e.g. 1.0 = 1% under).",
    )
    competitive_floor_margin_pct = fields.Float(
        "Floor Margin %",
        default=15.0,
        help="Never price below cost + this margin percentage.",
    )
    price_push_enabled = fields.Boolean("Auto Price Push", default=False)
    last_price_sync_date = fields.Datetime("Last Price Sync", readonly=True)
    amz_listing_ids = fields.One2many("amz.listing", "backend_id")

    def action_import_listings(self):
        """Pull active listings from Amazon and create/update amz.listing records."""
        self.ensure_one()
        if not self.seller_id:
            raise UserError(
                self.env._(
                    "Amazon Seller ID is required to import listings. "
                    "Set it in the Pricing section."
                )
            )
        from sp_api.api import ListingsItems

        api = self._get_api(ListingsItems)
        imported = 0
        next_token = None

        while True:
            kwargs = {
                "sellerId": self.seller_id,
                "marketplaceIds": [self.marketplace_id],
            }
            if next_token:
                kwargs["pageToken"] = next_token

            result = api.search_listings_items(**kwargs)
            payload = result.payload

            for item in payload.get("items", []):
                sku = item.get("sku")
                if not sku:
                    continue
                asin = None
                summaries = item.get("summaries", [])
                if summaries:
                    asin = summaries[0].get("asin")
                product = self.env["product.product"].search(
                    [("default_code", "=", sku)], limit=1
                )
                if not product:
                    _logger.warning("no product found for SKU %s; skipping", sku)
                    continue
                self.env["amz.listing"]._upsert(self, product, sku, asin)
                imported += 1

            next_token = payload.get("pagination", {}).get("nextToken")
            if not next_token:
                break

        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": "Listings Imported",
                "message": f"{imported} listing(s) imported from Amazon.",
                "type": "success",
            },
        }

    def action_push_prices(self):
        """Queue a price push job for all active listings."""
        self.ensure_one()
        if not self.seller_id:
            raise UserError(self.env._("Amazon Seller ID is required to push prices."))
        self.with_delay(description=f"Push prices for {self.name}")._push_prices()
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": "Price Push Queued",
                "message": "Price synchronisation job has been queued.",
                "type": "info",
            },
        }

    def _push_prices(self):
        """Push computed prices to Amazon via Listings Items API PATCH."""
        self.ensure_one()
        from sp_api.api import ListingsItems

        api = self._get_api(ListingsItems)
        active_listings = self.amz_listing_ids.filtered("active")
        pushed = 0

        for listing in active_listings:
            price = self._compute_listing_price(listing)
            if price is None:
                continue
            try:
                self._patch_listing_price_to_api(api, listing, price)
                listing.write(
                    {
                        "current_list_price": price,
                        "computed_target_price": price,
                        "last_price_push_date": fields.Datetime.now(),
                    }
                )
                pushed += 1
            except Exception as exc:
                _logger.warning(
                    "price push failed for SKU %s on backend %s: %s",
                    listing.seller_sku,
                    self.name,
                    exc,
                )

        _logger.info(
            "pushed prices for %d/%d listings on backend %s",
            pushed,
            len(active_listings),
            self.name,
        )

    def _patch_listing_price_to_api(self, api, listing, price):
        """Execute a single purchasable_offer PATCH via the Listings Items API."""
        api.patch_listings_item(
            sellerId=self.seller_id,
            sku=listing.seller_sku,
            marketplaceIds=[self.marketplace_id],
            body={
                "productType": "PRODUCT",
                "patches": [
                    {
                        "op": "replace",
                        "path": "/attributes/purchasable_offer",
                        "value": [
                            {
                                "currency": listing.currency_id.name or "USD",
                                "our_price": [
                                    {"schedule": [{"value_with_tax": price}]}
                                ],
                            }
                        ],
                    }
                ],
            },
        )

    def _compute_listing_price(self, listing):
        """Return target price for a listing based on pricing_mode."""
        if self.pricing_mode == "pricelist":
            if not self.pricelist_id:
                return None
            return self.pricelist_id._get_product_price(listing.product_id, 1.0)
        return None

    def sync_prices(self):
        """Full price sync cycle. Called by cron or manual trigger."""
        for backend in self.filtered("price_push_enabled"):
            backend.with_delay(
                description=f"Push prices for {backend.name}"
            )._push_prices()

    def _import_order(self, amazon_order_id):
        """Auto-create amz.listing for any new SKUs seen in the imported order."""
        super()._import_order(amazon_order_id)
        amz_order = self.env["amz.order"].search(
            [("backend_id", "=", self.id), ("amz_order_id", "=", amazon_order_id)],
            limit=1,
        )
        if not amz_order:
            return
        for line in amz_order.amz_order_line_ids:
            if not line.seller_sku:
                continue
            product = self.env["product.product"].search(
                [("default_code", "=", line.seller_sku)], limit=1
            )
            if not product:
                continue
            self.env["amz.listing"]._upsert(self, product, line.seller_sku, line.asin)
