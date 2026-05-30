import logging

from odoo import fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

# Amazon FulfillmentOrderStatus → Odoo state.
STATUS_MAP = {
    "New": "processing",
    "Received": "processing",
    "Planning": "processing",
    "Processing": "processing",
    "Complete": "complete",
    "CompletePartialled": "complete",
    "Cancelled": "cancelled",
    "Unfulfillable": "invalid",
    "Invalid": "invalid",
}


class AmzFulfillmentOrder(models.Model):
    _name = "amz.fulfillment.order"
    _description = "Amazon Multi-Channel Fulfillment Order"
    _order = "create_date desc"

    name = fields.Char(
        "Fulfillment Order ID",
        required=True,
        copy=False,
        default="New",
        help="The sellerFulfillmentOrderId submitted to Amazon.",
    )
    picking_id = fields.Many2one(
        "stock.picking", "Delivery", required=True, ondelete="cascade", index=True
    )
    backend_id = fields.Many2one("amz.backend", "Backend", required=True, index=True)
    partner_id = fields.Many2one("res.partner", "Ship To", required=True)
    shipping_speed = fields.Selection(
        [
            ("Standard", "Standard"),
            ("Expedited", "Expedited"),
            ("Priority", "Priority"),
        ],
        default="Standard",
        required=True,
    )
    displayable_order_id = fields.Char()
    displayable_order_comment = fields.Char()
    amazon_status = fields.Char(readonly=True)
    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("submitted", "Submitted"),
            ("processing", "Processing"),
            ("complete", "Complete"),
            ("cancelled", "Cancelled"),
            ("invalid", "Invalid"),
        ],
        default="draft",
        required=True,
        index=True,
    )
    line_ids = fields.One2many(
        "amz.fulfillment.order.line", "fulfillment_order_id", "Items"
    )
    tracking_numbers = fields.Char(readonly=True)
    carrier = fields.Char(readonly=True)

    def action_submit(self):
        self.ensure_one()
        if self.state != "draft":
            raise UserError(self.env._("Only draft orders can be submitted."))
        if not self.line_ids:
            raise UserError(self.env._("Add at least one item before submitting."))
        self.backend_id._amz_create_fulfillment_order(self)
        self.state = "submitted"

    def action_check_status(self):
        self._sync_status()

    def _cron_sync_status(self):
        """Cron entry point: poll each order, isolating per-order failures so a
        single transient SP-API error doesn't roll back the whole batch."""
        for order in self:
            try:
                order._sync_status()
            except UserError as exc:
                _logger.warning("MCF status sync failed for %s: %s", order.name, exc)

    def action_cancel(self):
        self.ensure_one()
        if self.state in ("complete", "cancelled"):
            raise UserError(
                self.env._("A complete or cancelled order cannot be cancelled.")
            )
        if self.state != "draft":
            self.backend_id._amz_cancel_fulfillment_order(self)
        self.state = "cancelled"

    def _sync_status(self):
        """Pull the latest status + tracking from Amazon and reflect it back."""
        for order in self:
            payload = order.backend_id._amz_get_fulfillment_order(order)
            status = (payload.get("fulfillmentOrder") or {}).get(
                "fulfillmentOrderStatus"
            )
            if status:
                order.amazon_status = status
                order.state = STATUS_MAP.get(status, order.state)
            tracks, carriers = [], []
            for shipment in payload.get("fulfillmentShipments") or []:
                for package in shipment.get("fulfillmentShipmentPackage") or []:
                    if package.get("trackingNumber"):
                        tracks.append(package["trackingNumber"])
                    if package.get("carrierCode"):
                        carriers.append(package["carrierCode"])
            if tracks:
                order.tracking_numbers = ", ".join(tracks)
                order.carrier = ", ".join(sorted(set(carriers)))
                # Reflect the Amazon tracking onto the Odoo delivery.
                if not order.picking_id.carrier_tracking_ref:
                    order.picking_id.carrier_tracking_ref = tracks[0]


class AmzFulfillmentOrderLine(models.Model):
    _name = "amz.fulfillment.order.line"
    _description = "Amazon Multi-Channel Fulfillment Order Line"

    fulfillment_order_id = fields.Many2one(
        "amz.fulfillment.order", required=True, ondelete="cascade"
    )
    product_id = fields.Many2one("product.product", "Product")
    seller_sku = fields.Char("Seller SKU", required=True)
    item_id = fields.Char(
        "Item ID",
        required=True,
        help="sellerFulfillmentOrderItemId — unique per item in the order.",
    )
    quantity = fields.Float(default=1.0)
