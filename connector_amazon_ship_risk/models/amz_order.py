from pytz import utc

from odoo import fields, models

# Statuses where a merchant order still has to be shipped by us.
OPEN_MFN_STATUSES = (
    "PendingAvailability",
    "Pending",
    "Unshipped",
    "PartiallyShipped",
)


class AmzOrder(models.Model):
    _inherit = "amz.order"

    latest_ship_date = fields.Datetime(
        "Ship-by Cutoff",
        index=True,
        help="Latest date Amazon expects the order to ship (from the SP-API "
        "order). The ship-risk countdown runs against this.",
    )
    earliest_ship_date = fields.Datetime()
    ship_deadline_hours = fields.Float(
        "Hours to Cutoff",
        readonly=True,
        help="Hours left until the ship-by cutoff (business hours if the "
        "backend has a shipping calendar; 0 once the cutoff has passed). "
        "Refreshed by the ship-risk cron.",
    )
    ship_risk = fields.Selection(
        [
            ("none", "—"),
            ("on_track", "On Track"),
            ("at_risk", "At Risk"),
            ("blocked", "Stock Blocked"),
            ("overdue", "Overdue"),
        ],
        default="none",
        index=True,
        readonly=True,
    )

    def _delivery_ready(self):
        """Whether the order can physically ship now.

        True unless a pending outgoing picking is not fully reserved (a stock
        problem). No linked picking → nothing blocks us, so the clock governs.
        """
        self.ensure_one()
        if not self.sale_order_id:
            return True
        pending = self.sale_order_id.picking_ids.filtered(
            lambda p: p.picking_type_id.code == "outgoing"
            and p.state not in ("done", "cancel")
        )
        return all(p.state == "assigned" for p in pending)

    def _hours_to_cutoff(self, now):
        self.ensure_one()
        cutoff = self.latest_ship_date
        if not cutoff or now >= cutoff:
            return 0.0
        calendar = self.backend_id.ship_risk_calendar_id
        if calendar:
            return calendar.get_work_hours_count(
                utc.localize(now), utc.localize(cutoff)
            )
        return (cutoff - now).total_seconds() / 3600.0

    def _update_ship_risk(self):
        """Recompute ship-risk for merchant-fulfilled, still-open orders.

        Time-dependent, so it is written by this method (cron + on import)
        rather than a reactive compute that would never refresh as the clock
        moves toward the cutoff.
        """
        now = fields.Datetime.now()
        for order in self:
            risk, hours = "none", 0.0
            if (
                order.fulfillment_channel == "MFN"
                and order.amazon_status in OPEN_MFN_STATUSES
            ):
                hours = order._hours_to_cutoff(now)
                threshold = order.backend_id.ship_risk_threshold_hours
                if order.latest_ship_date and now > order.latest_ship_date:
                    risk = "overdue"
                elif not order._delivery_ready():
                    risk = "blocked"
                elif order.latest_ship_date and hours <= threshold:
                    risk = "at_risk"
                else:
                    risk = "on_track"
            order.ship_risk = risk
            order.ship_deadline_hours = hours
