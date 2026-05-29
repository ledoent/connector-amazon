from odoo import fields, models


class AmazonSettlementReconciliation(models.Model):
    _name = "amz.settlement.reconciliation"
    _description = "Amazon Settlement Reconciliation"
    _order = "settlement_group_id desc, amz_order_id"

    settlement_group_id = fields.Many2one(
        "amz.settlement.group",
        required=True,
        index=True,
        ondelete="cascade",
    )
    backend_id = fields.Many2one(
        "amz.backend",
        related="settlement_group_id.backend_id",
        store=True,
    )
    amz_order_id = fields.Char("Amazon Order ID", index=True)
    order_id = fields.Many2one("amz.order", "Amazon Order", ondelete="set null")
    invoice_id = fields.Many2one("account.move", ondelete="set null")
    settled_principal = fields.Monetary(currency_field="currency_id")
    invoiced_total = fields.Monetary("Invoiced", currency_field="currency_id")
    variance = fields.Monetary(currency_field="currency_id")
    state = fields.Selection(
        [
            ("matched", "Matched"),
            ("variance", "Variance"),
            ("no_invoice", "No Invoice"),
        ],
        default="no_invoice",
        index=True,
    )
    currency_id = fields.Many2one(
        "res.currency",
        related="settlement_group_id.currency_id",
        store=True,
    )
