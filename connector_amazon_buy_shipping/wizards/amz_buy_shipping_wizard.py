from odoo import api, fields, models
from odoo.exceptions import UserError


class AmzBuyShippingWizard(models.TransientModel):
    _name = "amz.buy.shipping.wizard"
    _description = "Buy Amazon Shipping"

    picking_id = fields.Many2one("stock.picking", required=True)
    backend_id = fields.Many2one("amz.backend", compute="_compute_backend", store=True)
    weight = fields.Float(required=True)
    weight_unit = fields.Selection(related="backend_id.weight_unit")
    package_length = fields.Float("Length", required=True)
    package_width = fields.Float("Width", required=True)
    package_height = fields.Float("Height", required=True)
    dimension_unit = fields.Selection(related="backend_id.dimension_unit")
    currency_id = fields.Many2one(
        "res.currency", default=lambda self: self.env.company.currency_id
    )
    rate_line_ids = fields.One2many(
        "amz.buy.shipping.rate", "wizard_id", "Shipping Rates"
    )
    rates_fetched = fields.Boolean()

    @api.depends("picking_id")
    def _compute_backend(self):
        amz = self.env["amz.order"]
        for wiz in self:
            order = (
                amz.search([("sale_order_id", "=", wiz.picking_id.sale_id.id)], limit=1)
                if wiz.picking_id.sale_id
                else amz
            )
            wiz.backend_id = order.backend_id

    @api.model
    def default_get(self, fields_list):
        vals = super().default_get(fields_list)
        picking = self.env["stock.picking"].browse(vals.get("picking_id"))
        backend = self.env["amz.order"]
        order = (
            backend.search([("sale_order_id", "=", picking.sale_id.id)], limit=1)
            if picking.sale_id
            else backend
        )
        be = order.backend_id
        # Package weight: sum of moved product weights, fall back to the default.
        weight = sum(
            (m.product_id.weight or 0.0) * m.product_uom_qty for m in picking.move_ids
        )
        vals["weight"] = weight or (be.default_package_weight if be else 16.0)
        vals["package_length"] = be.default_package_length if be else 10.0
        vals["package_width"] = be.default_package_width if be else 8.0
        vals["package_height"] = be.default_package_height if be else 4.0
        return vals

    def _reload(self):
        return {
            "type": "ir.actions.act_window",
            "res_model": self._name,
            "res_id": self.id,
            "view_mode": "form",
            "target": "new",
        }

    def action_get_rates(self):
        self.ensure_one()
        if not self.backend_id:
            raise UserError(
                self.env._("This delivery is not linked to an Amazon backend.")
            )
        self.rate_line_ids.unlink()
        rates = self.backend_id._amz_get_shipping_rates(
            self.picking_id,
            self.weight,
            self.package_length,
            self.package_width,
            self.package_height,
        )
        self.rate_line_ids = [
            (
                0,
                0,
                {
                    "shipping_service_id": r["shipping_service_id"],
                    "shipping_service_offer_id": r["shipping_service_offer_id"],
                    "carrier_name": r["carrier_name"],
                    "service_name": r["service_name"],
                    "cost": r["cost"],
                    "delivery_date": r["delivery_date"],
                },
            )
            for r in rates
        ]
        self.rates_fetched = True
        return self._reload()

    def _purchase(self, rate_line):
        self.ensure_one()
        if self.picking_id.amazon_label_purchased:
            raise UserError(
                self.env._("A label has already been purchased for this delivery.")
            )
        res = self.backend_id._amz_purchase_label(
            self.picking_id,
            self.weight,
            self.package_length,
            self.package_width,
            self.package_height,
            rate_line.shipping_service_id,
            rate_line.shipping_service_offer_id,
        )
        if not res.get("tracking_number"):
            raise UserError(
                self.env._("Amazon did not return a tracking number for the label.")
            )
        attachment = self.env["ir.attachment"]
        if res.get("label_contents"):
            ext = (res.get("label_type") or "pdf").lower()
            ref = res.get("amazon_shipment_id") or self.picking_id.name
            attachment = attachment.create(
                {
                    "name": f"amazon-label-{ref}.{ext}",
                    "type": "binary",
                    "datas": res["label_contents"],
                    "res_model": "stock.picking",
                    "res_id": self.picking_id.id,
                }
            )
        currency = (
            self.env["res.currency"].search(
                [("name", "=", res["currency_name"])], limit=1
            )
            or self.env.company.currency_id
        )
        shipment = self.env["amz.shipment"].create(
            {
                "picking_id": self.picking_id.id,
                "order_id": res.get("order_id"),
                "backend_id": self.backend_id.id,
                "amazon_shipment_id": res.get("amazon_shipment_id"),
                "tracking_number": res["tracking_number"],
                "carrier_name": res.get("carrier_name"),
                "service_name": res.get("service_name"),
                "cost": res.get("cost", 0.0),
                "currency_id": currency.id,
                "label_attachment_id": attachment.id,
            }
        )
        # Tracking flows to Amazon already (create_shipment confirms it); record
        # it on the picking and flag so _stock doesn't double-confirm.
        self.picking_id.write(
            {
                "carrier_tracking_ref": res["tracking_number"],
                "amazon_label_purchased": True,
            }
        )
        return shipment


class AmzBuyShippingRate(models.TransientModel):
    _name = "amz.buy.shipping.rate"
    _description = "Amazon Shipping Rate Option"
    _order = "cost"

    wizard_id = fields.Many2one(
        "amz.buy.shipping.wizard", required=True, ondelete="cascade"
    )
    shipping_service_id = fields.Char()
    shipping_service_offer_id = fields.Char()
    carrier_name = fields.Char()
    service_name = fields.Char("Service")
    cost = fields.Monetary(currency_field="currency_id")
    currency_id = fields.Many2one(related="wizard_id.currency_id")
    delivery_date = fields.Char("Est. Delivery")

    def action_buy(self):
        self.ensure_one()
        shipment = self.wizard_id._purchase(self)
        return {
            "type": "ir.actions.act_window",
            "name": "Amazon Shipment",
            "res_model": "amz.shipment",
            "res_id": shipment.id,
            "view_mode": "form",
            "target": "current",
        }
