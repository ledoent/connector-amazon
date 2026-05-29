import logging

from odoo import fields, models

_logger = logging.getLogger(__name__)


class AmzBackend(models.Model):
    _inherit = "amz.backend"

    last_fee_sync_date = fields.Datetime("Last Fee Sync", readonly=True)

    def action_sync_fees(self):
        self.ensure_one()
        updated = self._sync_fees()
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "type": "success",
                "message": f"{updated} listing(s) updated with fee estimates.",
                "next": {"type": "ir.actions.act_window_close"},
            },
        }

    def sync_fees(self):
        """Queue a fee sync per active backend. Called by cron or manual trigger."""
        for backend in self.filtered("active"):
            backend.with_delay(
                description=f"Sync Amazon fees for {backend.name}"
            )._sync_fees()

    def _sync_fees(self):
        """Pull GetMyFeesEstimate per listing and store the fee breakdown."""
        self.ensure_one()
        from sp_api.api import ProductFees
        from sp_api.base import SellingApiException

        api = self._get_api(ProductFees)
        listings = self.amz_listing_ids.filtered(
            lambda lst: lst.active and lst.seller_sku
        )
        updated = 0
        for listing in listings:
            price = listing.current_list_price or listing.buy_box_price
            if not price:
                continue
            try:
                res = api.get_product_fees_estimate_for_sku(
                    listing.seller_sku,
                    float(price),
                    currency=listing.currency_id.name or "USD",
                    is_amazon_fulfilled=listing.is_fba,
                    identifier=f"odoo-{listing.id}",
                )
            except SellingApiException as exc:
                _logger.warning(
                    "Fee estimate failed for %s: %s", listing.seller_sku, exc
                )
                continue
            vals = self._parse_fee_estimate(res.payload, price)
            if vals:
                listing.write(vals)
                updated += 1
        self.last_fee_sync_date = fields.Datetime.now()
        return updated

    @staticmethod
    def _parse_fee_estimate(payload, price):
        """Map a GetMyFeesEstimate payload to amz.listing fee fields."""
        result = (payload or {}).get("FeesEstimateResult") or {}
        if result.get("Status") != "Success":
            return {}
        details = (result.get("FeesEstimate") or {}).get("FeeDetailList") or []
        vals = {
            "fee_basis_price": price,
            "referral_fee": 0.0,
            "fulfillment_fee": 0.0,
            "variable_closing_fee": 0.0,
            "other_fees": 0.0,
            "last_fee_sync_date": fields.Datetime.now(),
        }
        for detail in details:
            ftype = detail.get("FeeType") or ""
            amount = float((detail.get("FeeAmount") or {}).get("Amount") or 0.0)
            if ftype == "ReferralFee":
                vals["referral_fee"] = amount
            elif ftype == "VariableClosingFee":
                vals["variable_closing_fee"] = amount
            elif "FBA" in ftype or "Fulfillment" in ftype:
                vals["fulfillment_fee"] += amount
            else:
                # Per-item, high-volume listing, etc. — keep it counted so the
                # total (and the floor) never understate the real fee load.
                vals["other_fees"] += amount
        return vals

    # ── Fee-aware repricing floor ──────────────────────────────────────────────

    def _compute_competitive_price(self, listing):
        """Raise the repricing floor so net margin clears the target *after*
        Amazon's real fees, not just cost + margin."""
        target = super()._compute_competitive_price(listing)
        if target is None:
            return None
        floor = self._fee_aware_floor(listing)
        if floor:
            target = max(target, floor)
        return target

    def _fee_aware_floor(self, listing):
        """Lowest price whose post-fee net margin still clears the floor margin.

        Solves P - cost - referral%*P - fixed >= margin%*P for P, i.e.
        P = (cost + fixed) / (1 - referral% - margin%).
        """
        self.ensure_one()
        cost = listing.product_id.standard_price
        if not cost or not listing.fee_basis_price:
            return None
        margin = self.competitive_floor_margin_pct / 100.0
        denom = 1.0 - listing.referral_fee_pct - margin
        if denom <= 0:
            return None
        # Everything that isn't the price-scaled referral fee is fixed.
        fixed = listing.total_fees - listing.referral_fee
        return (cost + fixed) / denom
