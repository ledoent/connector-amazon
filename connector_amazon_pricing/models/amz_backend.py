import logging

from odoo import fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

# Amazon GetCompetitivePricing accepts up to 20 ASINs per request.
_COMPETITIVE_PRICE_BATCH = 20


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

    def action_sync_competitive_prices(self):
        """Queue a competitive price pull job for this backend."""
        self.ensure_one()
        self.with_delay(
            description=f"Pull competitive prices for {self.name}"
        )._sync_competitive_prices()
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": "Sync Queued",
                "message": "Competitive price pull has been queued.",
                "type": "info",
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

    def _sync_competitive_prices(self):
        """Pull buy-box prices from Amazon ProductPricing API and update amz.listing."""
        self.ensure_one()
        from sp_api.api import ProductPricing

        api = self._get_api(ProductPricing)
        listings = self.amz_listing_ids.filtered(lambda lst: lst.active and lst.asin)
        if not listings:
            return

        updated = 0
        for i in range(0, len(listings), _COMPETITIVE_PRICE_BATCH):
            batch = listings[i : i + _COMPETITIVE_PRICE_BATCH]
            try:
                result = api.get_competitive_pricing(
                    asin_list=batch.mapped("asin"),
                    item_type="Asin",
                    marketplaceIds=[self.marketplace_id],
                )
                for item in result.payload:
                    asin = item.get("ASIN")
                    competitive_prices = (
                        item.get("Product", {})
                        .get("CompetitivePricing", {})
                        .get("CompetitivePrices", [])
                    )
                    # CompetitivePriceId "1" = buy box winner
                    buy_box = next(
                        (
                            p
                            for p in competitive_prices
                            if p.get("CompetitivePriceId") == "1"
                        ),
                        None,
                    )
                    if not buy_box:
                        continue
                    amount = float(
                        buy_box.get("Price", {})
                        .get("ListingPrice", {})
                        .get("Amount", 0)
                    )
                    listing = batch.filtered(lambda lst, a=asin: lst.asin == a)
                    if not listing:
                        continue
                    listing.write(
                        {
                            "buy_box_price": amount,
                            "buy_box_winner": (
                                "us"
                                if buy_box.get("belongsToRequester")
                                else "competitor"
                            ),
                            "last_price_pull_date": fields.Datetime.now(),
                        }
                    )
                    updated += 1
            except Exception as exc:
                _logger.warning(
                    "competitive price pull failed for backend %s: %s", self.name, exc
                )

        _logger.info(
            "updated buy-box prices for %d listing(s) on backend %s",
            updated,
            self.name,
        )
        self.last_price_sync_date = fields.Datetime.now()

    def _compute_listing_price(self, listing):
        """Return target price for a listing based on pricing_mode."""
        if self.pricing_mode == "pricelist":
            if not self.pricelist_id:
                return None
            return self.pricelist_id._get_product_price(listing.product_id, 1.0)
        if self.pricing_mode == "competitive":
            return self._compute_competitive_price(listing)
        return None

    def _compute_competitive_price(self, listing):
        """Return competitive target price, clamped to cost+floor."""
        if not listing.buy_box_price:
            return None

        if self.competitive_rule == "match_buy_box":
            target = listing.buy_box_price
        elif self.competitive_rule == "undercut_buy_box":
            target = listing.buy_box_price * (
                1.0 - self.competitive_undercut_pct / 100.0
            )
        else:
            # floor_cost_plus — compete at buy box, floor prevents below-cost sales
            target = listing.buy_box_price

        # Apply floor to all rules: never price below cost + floor margin.
        # If buy box is below floor, price at floor rather than matching.
        cost = listing.product_id.standard_price
        if cost:
            floor = cost * (1.0 + self.competitive_floor_margin_pct / 100.0)
            target = max(target, floor)

        return target

    def sync_prices(self):
        """Full price sync cycle. Called by cron or manual trigger."""
        for backend in self.filtered("price_push_enabled"):
            backend.with_delay(
                description=f"Sync prices for {backend.name}"
            )._do_sync_prices()

    def _do_sync_prices(self):
        """Pull competitive prices then push in a single job (preserves ordering)."""
        self.ensure_one()
        if self.pricing_mode == "competitive":
            self._sync_competitive_prices()
        self._push_prices()

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
