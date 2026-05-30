from odoo import api, fields, models


class StockPicking(models.Model):
    _inherit = "stock.picking"

    amazon_label_purchased = fields.Boolean(readonly=True, copy=False)
    amz_shipment_ids = fields.One2many("amz.shipment", "picking_id", "Amazon Shipments")
    is_amazon_order = fields.Boolean(compute="_compute_is_amazon_order")

    @api.depends("sale_id")
    def _compute_is_amazon_order(self):
        amz = self.env["amz.order"]
        for picking in self:
            picking.is_amazon_order = bool(picking.sale_id) and bool(
                amz.search_count([("sale_order_id", "=", picking.sale_id.id)])
            )

    def _enqueue_amazon_tracking_push(self):
        # Labels bought through Amazon Buy Shipping are already confirmed to
        # Amazon by create_shipment — don't double-confirm via ConfirmShipment.
        pickings = self.filtered(lambda p: not p.amazon_label_purchased)
        return super(StockPicking, pickings)._enqueue_amazon_tracking_push()

    def action_amz_buy_shipping(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": "Buy Amazon Shipping",
            "res_model": "amz.buy.shipping.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {"default_picking_id": self.id},
        }
