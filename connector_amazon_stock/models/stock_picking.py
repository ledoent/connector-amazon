import logging

from odoo import models

_logger = logging.getLogger(__name__)


class StockPicking(models.Model):
    _inherit = "stock.picking"

    def _action_done(self):
        res = super()._action_done()
        self._enqueue_amazon_tracking_push()
        return res

    def _enqueue_amazon_tracking_push(self):
        """For pickings tied to Amazon orders, enqueue a tracking push job."""
        for picking in self:
            if not picking.carrier_tracking_ref:
                continue
            sale = picking.sale_id
            if not sale:
                continue
            amz_order = self.env["amz.order"].search(
                [("sale_order_id", "=", sale.id)], limit=1
            )
            if not amz_order:
                continue
            amz_order.backend_id.with_delay(
                description=f"Push tracking {picking.carrier_tracking_ref} "
                f"for Amazon order {amz_order.amz_order_id}"
            )._confirm_shipment(amz_order.amz_order_id, picking.id)
