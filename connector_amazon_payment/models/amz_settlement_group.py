from odoo import fields, models


class AmazonSettlementGroup(models.Model):
    _name = "amz.settlement.group"
    _description = "Amazon Settlement Group"
    _rec_name = "amazon_group_id"
    _order = "fund_transfer_date desc"

    backend_id = fields.Many2one(
        "amz.backend",
        required=True,
        index=True,
        ondelete="cascade",
    )
    amazon_group_id = fields.Char("Settlement Group ID", required=True, index=True)
    processing_status = fields.Char(readonly=True)
    fund_transfer_date = fields.Datetime(readonly=True)
    original_total = fields.Monetary(currency_field="currency_id")
    converted_total = fields.Monetary(currency_field="currency_id")
    currency_id = fields.Many2one("res.currency")
    account_move_id = fields.Many2one(
        "account.move",
        "Journal Entry",
        readonly=True,
        ondelete="set null",
    )
    financial_event_ids = fields.One2many(
        "amz.financial.event",
        "settlement_group_id",
        "Financial Events",
    )
    reconciliation_ids = fields.One2many(
        "amz.settlement.reconciliation",
        "settlement_group_id",
        "Reconciliation",
    )

    _amz_settlement_group_uniq = models.Constraint(
        "UNIQUE(backend_id, amazon_group_id)",
        "Settlement group already imported for this backend.",
    )
