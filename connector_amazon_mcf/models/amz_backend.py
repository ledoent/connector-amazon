import logging
from contextlib import contextmanager

from odoo import fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class AmzBackend(models.Model):
    _inherit = "amz.backend"

    mcf_default_speed = fields.Selection(
        [
            ("Standard", "Standard"),
            ("Expedited", "Expedited"),
            ("Priority", "Priority"),
        ],
        "MCF Default Speed",
        default="Standard",
    )

    # ── Fulfillment Outbound (Multi-Channel Fulfillment) ───────────────────────

    def _amz_mcf_body(self, fulfillment_order):
        """Build the createFulfillmentOrder request body."""
        self.ensure_one()
        addr = fulfillment_order.partner_id
        order_date = fulfillment_order.create_date or fields.Datetime.now()
        return {
            "marketplaceId": self.marketplace_id,
            "sellerFulfillmentOrderId": fulfillment_order.name,
            "displayableOrderId": fulfillment_order.displayable_order_id
            or fulfillment_order.name,
            "displayableOrderDate": order_date.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "displayableOrderComment": fulfillment_order.displayable_order_comment
            or "Shipped by Amazon Multi-Channel Fulfillment",
            "shippingSpeedCategory": fulfillment_order.shipping_speed,
            "destinationAddress": {
                "name": (addr.name or "")[:50],
                "addressLine1": addr.street or "",
                "addressLine2": addr.street2 or "",
                "city": addr.city or "",
                "stateOrRegion": addr.state_id.code or addr.state_id.name or "",
                "postalCode": addr.zip or "",
                "countryCode": addr.country_id.code or "US",
                "phone": addr.phone or "",
            },
            "items": [
                {
                    "sellerSku": line.seller_sku,
                    "sellerFulfillmentOrderItemId": line.item_id,
                    "quantity": int(line.quantity),
                }
                for line in fulfillment_order.line_ids
            ],
        }

    @contextmanager
    def _amz_fbo_api(self, error_message):
        """Yield a Fulfillment Outbound client, mapping SP-API errors raised by
        the wrapped call to a translated UserError. ``error_message`` is an
        already-translated string with a single ``%s`` placeholder."""
        self.ensure_one()
        from sp_api.api import FulfillmentOutbound
        from sp_api.base import SellingApiException

        api = self._get_api(FulfillmentOutbound)
        try:
            yield api
        except SellingApiException as exc:
            raise UserError(error_message % exc) from exc

    def _amz_create_fulfillment_order(self, fulfillment_order):
        with self._amz_fbo_api(
            self.env._("Amazon rejected the fulfillment order: %s")
        ) as api:
            api.create_fulfillment_order(**self._amz_mcf_body(fulfillment_order))

    def _amz_get_fulfillment_order(self, fulfillment_order):
        with self._amz_fbo_api(
            self.env._("Could not fetch the fulfillment order status: %s")
        ) as api:
            res = api.get_fulfillment_order(fulfillment_order.name)
        return res.payload or {}

    def _amz_cancel_fulfillment_order(self, fulfillment_order):
        with self._amz_fbo_api(
            self.env._("Amazon could not cancel the fulfillment order: %s")
        ) as api:
            api.cancel_fulfillment_order(fulfillment_order.name)
