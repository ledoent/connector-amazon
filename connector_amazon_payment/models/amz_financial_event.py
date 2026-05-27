from odoo import fields, models


class AmazonFinancialEvent(models.Model):
    _name = "amz.financial.event"
    _description = "Amazon Financial Event"
    _order = "posted_date desc"

    settlement_group_id = fields.Many2one(
        "amz.settlement.group",
        required=True,
        ondelete="cascade",
        index=True,
    )
    backend_id = fields.Many2one(
        "amz.backend",
        related="settlement_group_id.backend_id",
        store=True,
    )
    event_type = fields.Selection(
        [
            ("shipment", "Shipment"),
            ("refund", "Refund"),
            ("referral_fee", "Referral Fee"),
            ("fba_fee", "FBA Fee"),
            ("advertising", "Advertising"),
            ("service_fee", "Service Fee"),
            ("other", "Other"),
        ],
        required=True,
    )
    amz_order_id = fields.Char("Amazon Order ID", index=True)
    posted_date = fields.Datetime()
    # Positive = income, negative = expense
    amount = fields.Monetary(currency_field="currency_id")
    fee_description = fields.Char()
    currency_id = fields.Many2one(
        "res.currency",
        related="settlement_group_id.currency_id",
        store=True,
    )
