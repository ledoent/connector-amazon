from datetime import timedelta

from odoo import api, fields, models


class AmazonDashboard(models.TransientModel):
    _name = "amz.dashboard"
    _description = "Amazon Dashboard"

    backend_id = fields.Many2one(
        "amz.backend",
        "Backend",
        help="Limit the KPIs to one backend. Empty = all active backends.",
    )
    currency_id = fields.Many2one(
        "res.currency", default=lambda self: self.env.company.currency_id
    )

    # ── Sales ─────────────────────────────────────────────────────────────────
    orders_total = fields.Integer("Orders", compute="_compute_kpis")
    orders_unshipped = fields.Integer("Unshipped", compute="_compute_kpis")
    # ── Pricing / repricing ───────────────────────────────────────────────────
    listings_total = fields.Integer("Listings", compute="_compute_kpis")
    listings_buybox_us = fields.Integer("Buy Box (Us)", compute="_compute_kpis")
    buybox_win_rate = fields.Float("Buy Box Win %", compute="_compute_kpis")
    price_changes_7d = fields.Integer("Price Changes (7d)", compute="_compute_kpis")
    offers_7d = fields.Integer("Competitor Offers (7d)", compute="_compute_kpis")
    # ── FBA ───────────────────────────────────────────────────────────────────
    fba_skus = fields.Integer("FBA SKUs", compute="_compute_kpis")
    fba_drift_skus = fields.Integer("FBA Drift SKUs", compute="_compute_kpis")
    fba_total_drift = fields.Float("FBA Total Drift", compute="_compute_kpis")
    # ── Settlements ───────────────────────────────────────────────────────────
    settlement_groups = fields.Integer("Settlements", compute="_compute_kpis")
    settlement_moves_draft = fields.Integer("Draft Entries", compute="_compute_kpis")
    recon_matched = fields.Integer("Matched", compute="_compute_kpis")
    recon_variance = fields.Integer("Variances", compute="_compute_kpis")
    recon_no_invoice = fields.Integer("No Invoice", compute="_compute_kpis")
    recon_variance_amount = fields.Monetary(
        "Variance Amount", currency_field="currency_id", compute="_compute_kpis"
    )
    # ── Returns ───────────────────────────────────────────────────────────────
    returns_open = fields.Integer("Open Returns", compute="_compute_kpis")
    returns_credited = fields.Integer("Credited Returns", compute="_compute_kpis")
    # ── Health ────────────────────────────────────────────────────────────────
    failed_jobs = fields.Integer(compute="_compute_kpis")
    last_order_sync = fields.Datetime(compute="_compute_kpis")
    last_settlement_sync = fields.Datetime(compute="_compute_kpis")
    last_return_sync = fields.Datetime(compute="_compute_kpis")
    last_fba_sync = fields.Datetime(compute="_compute_kpis")
    last_price_sync = fields.Datetime(compute="_compute_kpis")
    health_status = fields.Selection(
        [("ok", "OK"), ("attention", "Needs Attention")],
        "Health",
        compute="_compute_kpis",
    )

    def _backends(self):
        """Backends in scope: the selected one, else all active."""
        return self.backend_id or self.env["amz.backend"].search(
            [("active", "=", True)]
        )

    def _backend_domain(self):
        """Domain leaf restricting to the in-scope backends (for drill-downs)."""
        return [("backend_id", "in", self._backends().ids)]

    @staticmethod
    def _latest(records, field):
        dates = [d for d in records.mapped(field) if d]
        return max(dates) if dates else False

    @api.depends("backend_id")
    def _compute_kpis(self):
        for rec in self:
            backends = rec._backends()
            bdom = [("backend_id", "in", backends.ids)]
            cutoff = fields.Datetime.now() - timedelta(days=7)

            order = self.env["amz.order"]
            rec.orders_total = order.search_count(bdom)
            rec.orders_unshipped = order.search_count(
                bdom
                + [
                    (
                        "amazon_status",
                        "not in",
                        ["Shipped", "Canceled", "Unfulfillable"],
                    )
                ]
            )

            listing = self.env["amz.listing"]
            rec.listings_total = listing.search_count(bdom)
            rec.listings_buybox_us = listing.search_count(
                bdom + [("buy_box_winner", "=", "us")]
            )
            with_winner = listing.search_count(bdom + [("buy_box_winner", "!=", False)])
            # Fraction (0-1); the view renders it with widget="percentage".
            rec.buybox_win_rate = (
                rec.listings_buybox_us / with_winner if with_winner else 0.0
            )
            rec.price_changes_7d = self.env["amz.price.history"].search_count(
                bdom + [("date", ">=", cutoff)]
            )
            rec.offers_7d = self.env["amz.offer.snapshot"].search_count(
                bdom + [("date", ">=", cutoff)]
            )

            fba = self.env["amz.fba.inventory"]
            rec.fba_skus = fba.search_count(bdom)
            drift = fba.search(bdom + [("drift", "!=", 0)])
            rec.fba_drift_skus = len(drift)
            rec.fba_total_drift = sum(abs(d.drift) for d in drift)

            group = self.env["amz.settlement.group"]
            rec.settlement_groups = group.search_count(bdom)
            rec.settlement_moves_draft = group.search_count(
                bdom + [("account_move_id.state", "=", "draft")]
            )
            recon = self.env["amz.settlement.reconciliation"]
            rec.recon_matched = recon.search_count(bdom + [("state", "=", "matched")])
            rec.recon_variance = recon.search_count(bdom + [("state", "=", "variance")])
            rec.recon_no_invoice = recon.search_count(
                bdom + [("state", "=", "no_invoice")]
            )
            variances = recon.search(bdom + [("state", "=", "variance")])
            rec.recon_variance_amount = sum(abs(v.variance) for v in variances)

            ret = self.env["amz.return"]
            rec.returns_open = ret.search_count(
                bdom + [("state", "in", ["new", "picking_created"])]
            )
            rec.returns_credited = ret.search_count(
                bdom + [("state", "in", ["credited", "done"])]
            )

            # queue.job is not backend-scoped — failed jobs are a server-wide signal.
            rec.failed_jobs = self.env["queue.job"].search_count(
                [("state", "=", "failed")]
            )
            rec.last_order_sync = self._latest(backends, "last_import_date")
            rec.last_settlement_sync = self._latest(
                backends, "last_settlement_sync_date"
            )
            rec.last_return_sync = self._latest(backends, "last_return_sync_date")
            rec.last_fba_sync = self._latest(backends, "last_fba_sync_date")
            rec.last_price_sync = self._latest(backends, "last_price_sync_date")
            rec.health_status = (
                "attention"
                if rec.failed_jobs or rec.recon_variance or rec.fba_drift_skus
                else "ok"
            )

    # ── drill-downs ───────────────────────────────────────────────────────────

    def _action(self, name, model, domain, view_mode="list,form"):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": name,
            "res_model": model,
            "view_mode": view_mode,
            "domain": domain + self._backend_domain(),
        }

    def action_open_unshipped(self):
        return self._action(
            "Unshipped Orders",
            "amz.order",
            [("amazon_status", "not in", ["Shipped", "Canceled", "Unfulfillable"])],
        )

    def action_open_fba_drift(self):
        return self._action("FBA Drift", "amz.fba.inventory", [("drift", "!=", 0)])

    def action_open_recon_variance(self):
        return self._action(
            "Settlement Variances",
            "amz.settlement.reconciliation",
            [("state", "=", "variance")],
        )

    def action_open_returns_open(self):
        return self._action(
            "Open Returns",
            "amz.return",
            [("state", "in", ["new", "picking_created"])],
        )

    def action_open_price_changes(self):
        cutoff = fields.Datetime.now() - timedelta(days=7)
        return self._action(
            "Recent Price Changes", "amz.price.history", [("date", ">=", cutoff)]
        )

    def action_open_failed_jobs(self):
        # queue.job is server-wide (no backend scoping).
        return {
            "type": "ir.actions.act_window",
            "name": "Failed Jobs",
            "res_model": "queue.job",
            "view_mode": "list,form",
            "domain": [("state", "=", "failed")],
        }
