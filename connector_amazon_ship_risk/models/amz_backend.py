import datetime
import logging

from dateutil import parser as date_parser

from odoo import fields, models

_logger = logging.getLogger(__name__)


class AmzBackend(models.Model):
    _inherit = "amz.backend"

    ship_risk_threshold_hours = fields.Float(
        "Ship-Risk Threshold (hours)",
        default=24.0,
        help="An unshipped merchant order is flagged At Risk when fewer than "
        "this many hours remain before Amazon's ship-by cutoff.",
    )
    ship_risk_calendar_id = fields.Many2one(
        "resource.calendar",
        string="Shipping Calendar",
        help="If set, the hours-to-cutoff countdown counts working hours from "
        "this calendar instead of wall-clock time, so a Friday-evening cutoff "
        "with the weekend ahead reads as urgent.",
    )

    def _import_order(self, amazon_order_id):
        res = super()._import_order(amazon_order_id)
        self._amz_capture_ship_dates(amazon_order_id)
        return res

    def _amz_capture_ship_dates(self, amazon_order_id):
        """Capture the order-level ship-by cutoff + fulfillment channel.

        These live on the GetOrder summary, not the order-items payload the
        base import reads, so we fetch the order once more and then refresh
        the ship-risk state.
        """
        self.ensure_one()
        from sp_api.api import Orders
        from sp_api.base import SellingApiException

        order = self.env["amz.order"].search(
            [("backend_id", "=", self.id), ("amz_order_id", "=", amazon_order_id)],
            limit=1,
        )
        if not order:
            return
        try:
            data = self._get_api(Orders).get_order(amazon_order_id).payload or {}
        except SellingApiException as exc:
            _logger.warning("GetOrder failed for %s: %s", amazon_order_id, exc)
            return
        vals = {}
        latest = self._parse_amz_datetime(data.get("LatestShipDate"))
        earliest = self._parse_amz_datetime(data.get("EarliestShipDate"))
        if latest:
            vals["latest_ship_date"] = latest
        if earliest:
            vals["earliest_ship_date"] = earliest
        if data.get("FulfillmentChannel"):
            vals["fulfillment_channel"] = data["FulfillmentChannel"]
        if data.get("OrderStatus"):
            vals["amazon_status"] = data["OrderStatus"]
        if vals:
            order.write(vals)
        order._update_ship_risk()

    @staticmethod
    def _parse_amz_datetime(value):
        """Parse an SP-API ISO-8601 timestamp to a naive UTC datetime."""
        if not value:
            return False
        parsed = date_parser.isoparse(value)
        if parsed.tzinfo:
            parsed = parsed.astimezone(datetime.timezone.utc).replace(tzinfo=None)
        return parsed
