import logging

from odoo import models

_logger = logging.getLogger(__name__)

# SP-API carrier code mapping from Odoo delivery carrier names (case-insensitive prefix match)
_CARRIER_CODE_MAP = {
    "ups": "UPS",
    "usps": "USPS",
    "fedex": "FedEx",
    "dhl": "DHL",
    "amazon": "Amazon",
    "ontrac": "OnTrac",
    "lasership": "LaserShip",
    "uds": "UDS",
    "uds logistics": "UDS",
}


def _map_carrier_code(carrier_name):
    name_lower = (carrier_name or "").lower()
    for prefix, code in _CARRIER_CODE_MAP.items():
        if name_lower.startswith(prefix):
            return code
    return "Other"


class AmazonBackend(models.Model):
    _inherit = "amz.backend"

    def _confirm_shipment(self, amazon_order_id, picking_id):
        """Push carrier tracking number to Amazon ConfirmShipment endpoint."""
        self.ensure_one()
        from sp_api.api import Orders
        from sp_api.base import SellingApiException

        picking = self.env["stock.picking"].browse(picking_id)
        if not picking.exists():
            _logger.warning("Picking %s no longer exists; skipping tracking push.", picking_id)
            return

        tracking_ref = picking.carrier_tracking_ref
        if not tracking_ref:
            _logger.warning("Picking %s has no tracking ref; skipping.", picking_id)
            return

        carrier_name = picking.carrier_id.name if picking.carrier_id else ""
        carrier_code = _map_carrier_code(carrier_name)

        # Build order items list from amz.order.line
        amz_order = self.env["amz.order"].search(
            [("backend_id", "=", self.id), ("amz_order_id", "=", amazon_order_id)],
            limit=1,
        )
        order_items = [
            {"orderItemId": ln.order_item_id, "quantity": ln.quantity_ordered}
            for ln in amz_order.amz_order_line_ids
        ]

        api = self._get_api(Orders)

        try:
            api.confirm_shipment(
                order_id=amazon_order_id,
                payload={
                    "marketplaceId": self.marketplace_id,
                    "packageDetail": {
                        "packageReferenceId": picking.name,
                        "carrierCode": carrier_code,
                        "carrierName": carrier_name,
                        "trackingNumber": tracking_ref,
                        "shipDate": picking.date_done.strftime("%Y-%m-%dT%H:%M:%SZ"),
                        "orderItems": order_items,
                    },
                },
            )
            _logger.info(
                "Pushed tracking %s for Amazon order %s.",
                tracking_ref,
                amazon_order_id,
            )
        except SellingApiException as exc:
            _logger.error(
                "ConfirmShipment failed for Amazon order %s: %s",
                amazon_order_id,
                exc,
            )
            raise
