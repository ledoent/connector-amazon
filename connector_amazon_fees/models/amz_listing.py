from odoo import api, fields, models


class AmzListing(models.Model):
    _inherit = "amz.listing"

    is_fba = fields.Boolean(
        "FBA",
        help="Fulfilled by Amazon. Drives whether the fee estimate includes "
        "FBA fulfillment fees.",
    )
    # Raw fee components from GetMyFeesEstimate, computed at fee_basis_price.
    referral_fee = fields.Monetary(currency_field="currency_id", readonly=True)
    fulfillment_fee = fields.Monetary(currency_field="currency_id", readonly=True)
    variable_closing_fee = fields.Monetary(currency_field="currency_id", readonly=True)
    other_fees = fields.Monetary(
        currency_field="currency_id",
        readonly=True,
        help="Any fee type Amazon returns beyond the named ones "
        "(e.g. per-item fee), so total_fees never understates the real cost.",
    )
    fee_basis_price = fields.Monetary(
        currency_field="currency_id",
        readonly=True,
        help="The price the fee estimate was computed at.",
    )
    last_fee_sync_date = fields.Datetime(readonly=True)

    total_fees = fields.Monetary(
        currency_field="currency_id", compute="_compute_fees", store=True
    )
    referral_fee_pct = fields.Float(
        "Referral Fee %",
        compute="_compute_fees",
        store=True,
        help="Referral fee as a fraction of the basis price (0-1); drives the "
        "fee-aware repricing floor.",
    )
    est_net_proceeds = fields.Monetary(
        "Est. Net Proceeds",
        currency_field="currency_id",
        compute="_compute_fees",
        store=True,
    )
    est_net_margin = fields.Monetary(
        "Est. Net Margin",
        currency_field="currency_id",
        compute="_compute_fees",
        store=True,
    )
    est_margin_pct = fields.Float("Est. Margin %", compute="_compute_fees", store=True)
    below_target_margin = fields.Boolean(
        compute="_compute_below_target_margin", store=True
    )

    @api.depends(
        "referral_fee",
        "fulfillment_fee",
        "variable_closing_fee",
        "other_fees",
        "fee_basis_price",
        "product_id.standard_price",
    )
    def _compute_fees(self):
        for rec in self:
            rec.total_fees = (
                rec.referral_fee
                + rec.fulfillment_fee
                + rec.variable_closing_fee
                + rec.other_fees
            )
            basis = rec.fee_basis_price
            rec.referral_fee_pct = rec.referral_fee / basis if basis else 0.0
            rec.est_net_proceeds = basis - rec.total_fees if basis else 0.0
            cost = rec.product_id.standard_price
            rec.est_net_margin = rec.est_net_proceeds - cost if basis else 0.0
            rec.est_margin_pct = rec.est_net_margin / basis if basis else 0.0

    @api.depends("est_margin_pct", "backend_id.competitive_floor_margin_pct")
    def _compute_below_target_margin(self):
        for rec in self:
            target = rec.backend_id.competitive_floor_margin_pct / 100.0
            # Only flag listings that actually have a fee estimate.
            rec.below_target_margin = bool(rec.fee_basis_price) and (
                rec.est_margin_pct < target
            )
