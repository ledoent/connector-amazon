from odoo import fields, models
from odoo.exceptions import UserError


class StockPicking(models.Model):
    _inherit = "stock.picking"

    amz_fulfillment_order_ids = fields.One2many(
        "amz.fulfillment.order", "picking_id", "MCF Orders"
    )
    amz_mcf_count = fields.Integer(compute="_compute_amz_mcf_count")

    def _compute_amz_mcf_count(self):
        for picking in self:
            picking.amz_mcf_count = len(picking.amz_fulfillment_order_ids)

    def action_amz_mcf_fulfill(self):
        """Build a draft Amazon MCF order from this delivery's move lines.

        Each product is matched to its FBA seller SKU via amz.fba.inventory;
        a product with no FBA SKU can't be fulfilled from FBA stock.
        """
        self.ensure_one()
        backend = self.env["amz.backend"].search([("active", "=", True)], limit=1)
        if not backend:
            raise UserError(self.env._("No active Amazon backend is configured."))
        fba = self.env["amz.fba.inventory"]
        # Amazon requires a unique sellerFulfillmentOrderItemId per line, so the
        # same SKU must not appear twice. Aggregate demand per seller SKU.
        lines_by_sku = {}
        for move in self.move_ids:
            inventory = fba.search(
                [
                    ("backend_id", "=", backend.id),
                    ("product_id", "=", move.product_id.id),
                    ("seller_sku", "!=", False),
                ],
                limit=1,
            )
            if not inventory:
                raise UserError(
                    self.env._(
                        "No FBA SKU is known for %s, so it can't be fulfilled "
                        "from Amazon stock.",
                        move.product_id.display_name,
                    )
                )
            sku = inventory.seller_sku
            if sku in lines_by_sku:
                lines_by_sku[sku]["quantity"] += move.product_uom_qty
            else:
                lines_by_sku[sku] = {
                    "product_id": move.product_id.id,
                    "seller_sku": sku,
                    "item_id": sku,
                    "quantity": move.product_uom_qty,
                }
        line_vals = [(0, 0, vals) for vals in lines_by_sku.values()]
        order = self.env["amz.fulfillment.order"].create(
            {
                "name": self.name,
                "picking_id": self.id,
                "backend_id": backend.id,
                "partner_id": self.partner_id.id,
                "shipping_speed": backend.mcf_default_speed,
                "displayable_order_id": (
                    self.sale_id.name if self.sale_id else self.name
                ),
                "line_ids": line_vals,
            }
        )
        return {
            "type": "ir.actions.act_window",
            "name": "Amazon Fulfillment Order",
            "res_model": "amz.fulfillment.order",
            "res_id": order.id,
            "view_mode": "form",
            "target": "current",
        }

    def action_view_amz_mcf(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": "MCF Orders",
            "res_model": "amz.fulfillment.order",
            "view_mode": "list,form",
            "domain": [("picking_id", "=", self.id)],
        }
