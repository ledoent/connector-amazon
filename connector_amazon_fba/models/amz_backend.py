import logging

from odoo import fields, models

_logger = logging.getLogger(__name__)


def _int(value):
    """Coerce an SP-API quantity (possibly None/str) to a float."""
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


class AmazonBackend(models.Model):
    _inherit = "amz.backend"

    amazon_fba_enabled = fields.Boolean(
        "Sync FBA Inventory",
        default=False,
        help="Pull FBA on-hand from Amazon on the FBA cron for this backend.",
    )
    last_fba_sync_date = fields.Datetime("Last FBA Sync", readonly=True)
    amz_fba_inventory_ids = fields.One2many(
        "amz.fba.inventory", "backend_id", "FBA Inventory"
    )

    def action_sync_fba_inventory(self):
        """Queue an FBA inventory pull job for this backend."""
        self.ensure_one()
        self.with_delay(
            description=f"Sync FBA inventory for {self.name}"
        )._pull_fba_inventory()
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": "Sync Queued",
                "message": "FBA inventory pull has been queued.",
                "type": "info",
            },
        }

    def sync_fba_inventory(self):
        """Cron entry point — enqueue an FBA pull per enabled backend."""
        for backend in self.filtered(lambda b: b.active and b.amazon_fba_enabled):
            backend.with_delay(
                description=f"Sync FBA inventory for {backend.name}"
            )._pull_fba_inventory()

    def _pull_fba_inventory(self):
        """Pull FBA inventory summaries (read-only) and upsert drift records."""
        self.ensure_one()
        from sp_api.api import Inventories
        from sp_api.base import SellingApiException

        api = self._get_api(Inventories)
        next_token = None
        try:
            while True:
                kwargs = {
                    "details": True,
                    "granularityType": "Marketplace",
                    "granularityId": self.marketplace_id,
                    "marketplaceIds": [self.marketplace_id],
                }
                if next_token:
                    kwargs["nextToken"] = next_token
                result = api.get_inventory_summary_marketplace(**kwargs)
                payload = result.payload or {}
                for summary in payload.get("inventorySummaries", []):
                    self._upsert_fba_summary(summary)
                next_token = result.next_token
                if not next_token:
                    break
        except SellingApiException as exc:
            _logger.error(
                "Amazon FBA Inventory failed for backend %s: %s", self.name, exc
            )
            raise
        self.last_fba_sync_date = fields.Datetime.now()

    def _upsert_fba_summary(self, summary):
        sku = summary.get("sellerSku")
        if not sku:
            return
        details = summary.get("inventoryDetails", {}) or {}
        product = self.env["product.product"].search(
            [("default_code", "=", sku)], limit=1
        )
        fulfillable = _int(details.get("fulfillableQuantity"))
        inbound = (
            _int(details.get("inboundWorkingQuantity"))
            + _int(details.get("inboundShippedQuantity"))
            + _int(details.get("inboundReceivingQuantity"))
        )
        reserved = _int(
            (details.get("reservedQuantity") or {}).get("totalReservedQuantity")
        )
        unsellable = _int(
            (details.get("unfulfillableQuantity") or {}).get(
                "totalUnfulfillableQuantity"
            )
        )
        # Compare FBA stock against this backend's warehouse, not global on-hand.
        odoo_qty = (
            product.with_context(warehouse=self.warehouse_id.id).qty_available
            if product
            else 0.0
        )
        vals = {
            "asin": summary.get("asin"),
            "fnsku": summary.get("fnSku"),
            "product_id": product.id or False,
            "fulfillable_qty": fulfillable,
            "inbound_qty": inbound,
            "reserved_qty": reserved,
            "unsellable_qty": unsellable,
            "total_fba_qty": _int(summary.get("totalQuantity")),
            "odoo_qty": odoo_qty,
            "last_sync_date": fields.Datetime.now(),
        }
        existing = self.env["amz.fba.inventory"].search(
            [("backend_id", "=", self.id), ("seller_sku", "=", sku)], limit=1
        )
        if existing:
            existing.write(vals)
        else:
            self.env["amz.fba.inventory"].create(
                {**vals, "backend_id": self.id, "seller_sku": sku}
            )
