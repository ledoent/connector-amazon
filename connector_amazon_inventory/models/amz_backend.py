import logging

from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)


class AmazonBackend(models.Model):
    _inherit = "amz.backend"

    inventory_sync_enabled = fields.Boolean("Inventory Sync", default=False)
    inventory_location_ids = fields.Many2many(
        "stock.location",
        "amz_backend_stock_location_rel",
        "backend_id",
        "location_id",
        string="Fulfillment Locations",
        domain=[("usage", "=", "internal")],
        help=(
            "Stock locations counted toward Amazon FBM quantity. "
            "Leave empty to use the warehouse's default stock location."
        ),
    )
    inventory_expose_ratio = fields.Float(
        "Expose Ratio",
        default=1.0,
        help="Fraction of available stock to push to Amazon (0.0–1.0). E.g. 0.5 = 50%.",
    )
    inventory_min_reserve = fields.Integer(
        "Min Reserve",
        default=0,
        help="Units always held back for internal orders regardless of expose ratio.",
    )
    last_inventory_sync_date = fields.Datetime("Last Inventory Sync", readonly=True)

    @api.constrains("inventory_expose_ratio")
    def _check_expose_ratio(self):
        for rec in self:
            if not 0.0 <= rec.inventory_expose_ratio <= 1.0:
                raise ValidationError(
                    self.env._("Expose Ratio must be between 0.0 and 1.0.")
                )

    @api.constrains("inventory_min_reserve")
    def _check_min_reserve(self):
        for rec in self:
            if rec.inventory_min_reserve < 0:
                raise ValidationError(self.env._("Min Reserve cannot be negative."))

    def _compute_amazon_qty(self, product):
        """Return the quantity to push for a product.

        Computes: max(0, floor(free_qty * expose_ratio) - min_reserve)
        where free_qty = on-hand minus reserved across the configured locations.
        """
        self.ensure_one()
        if self.inventory_location_ids:
            location_ids = self.inventory_location_ids.ids
        else:
            location_ids = [self.warehouse_id.lot_stock_id.id]

        quants = self.env["stock.quant"].search(
            [("product_id", "=", product.id), ("location_id", "in", location_ids)]
        )
        free_qty = sum(max(0.0, q.quantity - q.reserved_quantity) for q in quants)
        return max(
            0,
            int(free_qty * self.inventory_expose_ratio) - self.inventory_min_reserve,
        )

    def _push_inventory(self):
        """Push FBM qty for all active listings where qty has changed."""
        self.ensure_one()
        from sp_api.api import ListingsItems

        api = self._get_api(ListingsItems)
        active = self.amz_listing_ids.filtered(
            lambda lst: lst.active and lst.inventory_sync_enabled
        )
        pushed = 0

        for listing in active:
            new_qty = self._compute_amazon_qty(listing.product_id)
            if new_qty == listing.last_pushed_qty:
                continue
            try:
                api.patch_listings_item(
                    sellerId=self.seller_id,
                    sku=listing.seller_sku,
                    marketplaceIds=[self.marketplace_id],
                    body={
                        "productType": "PRODUCT",
                        "patches": [
                            {
                                "op": "replace",
                                "path": "/attributes/fulfillment_availability",
                                "value": [
                                    {
                                        "fulfillment_channel_code": "DEFAULT",
                                        "quantity": new_qty,
                                    }
                                ],
                            }
                        ],
                    },
                )
                listing.write(
                    {
                        "last_pushed_qty": new_qty,
                        "last_inventory_push_date": fields.Datetime.now(),
                    }
                )
                pushed += 1
            except Exception as exc:
                _logger.warning(
                    "inventory push failed for SKU %s on backend %s: %s",
                    listing.seller_sku,
                    self.name,
                    exc,
                )

        self.last_inventory_sync_date = fields.Datetime.now()
        _logger.info(
            "pushed inventory for %d/%d listings on backend %s",
            pushed,
            len(active),
            self.name,
        )

    def action_push_inventory(self):
        """Manual button — enqueues _push_inventory job."""
        self.ensure_one()
        if not self.seller_id:
            raise UserError(
                self.env._("Amazon Seller ID is required to push inventory.")
            )
        self.with_delay(description=f"Push inventory for {self.name}")._push_inventory()
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": "Inventory Push Queued",
                "message": "Inventory synchronisation job has been queued.",
                "type": "info",
            },
        }

    def push_inventory(self):
        """Cron entry point — enqueues a job per enabled backend."""
        for backend in self.filtered("inventory_sync_enabled"):
            backend.with_delay(
                description=f"Push inventory for {backend.name}"
            )._push_inventory()
