from odoo import api, fields, models


class AmzShipment(models.Model):
    _name = "amz.shipment"
    _description = "Amazon Purchased Shipment"
    _order = "create_date desc"

    picking_id = fields.Many2one(
        "stock.picking", "Delivery", required=True, ondelete="cascade", index=True
    )
    order_id = fields.Many2one("amz.order", "Amazon Order", ondelete="set null")
    backend_id = fields.Many2one("amz.backend", "Backend", index=True)
    amazon_shipment_id = fields.Char("Amazon Shipment ID", index=True)
    tracking_number = fields.Char(index=True)
    carrier_name = fields.Char()
    service_name = fields.Char("Service")
    cost = fields.Monetary(currency_field="currency_id")
    currency_id = fields.Many2one(
        "res.currency", default=lambda self: self.env.company.currency_id
    )
    label_attachment_id = fields.Many2one("ir.attachment", "Label")

    @api.depends("tracking_number", "amazon_shipment_id")
    def _compute_display_name(self):
        for rec in self:
            rec.display_name = (
                rec.tracking_number or rec.amazon_shipment_id or "Shipment"
            )

    def action_download_label(self):
        self.ensure_one()
        if not self.label_attachment_id:
            return False
        return {
            "type": "ir.actions.act_url",
            "url": f"/web/content/{self.label_attachment_id.id}?download=true",
            "target": "self",
        }
