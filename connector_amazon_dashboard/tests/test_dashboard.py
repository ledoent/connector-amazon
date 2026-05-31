from odoo.tests.common import TransactionCase


class TestDashboard(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.warehouse = cls.env["stock.warehouse"].search([], limit=1)
        cls.backend = cls.env["amz.backend"].create(
            {
                "name": "Dash Backend",
                "client_id": "cid",
                "client_secret": "csec",
                "refresh_token": "rtok",
                "marketplace_id": "ATVPDKIKX0DER",
                "sandbox": True,
                "warehouse_id": cls.warehouse.id,
                "last_import_date": "2026-05-20 00:00:00",
                "last_fba_sync_date": "2026-05-21 00:00:00",
                "competitive_floor_margin_pct": 50.0,
            }
        )
        # A second, empty backend to prove the backend_id filter scopes counts.
        cls.other = cls.env["amz.backend"].create(
            {
                "name": "Other Backend",
                "client_id": "cid2",
                "client_secret": "csec2",
                "refresh_token": "rtok2",
                "marketplace_id": "ATVPDKIKX0DER",
                "sandbox": True,
                "warehouse_id": cls.warehouse.id,
            }
        )
        cls.product = cls.env["product.product"].create(
            {"name": "Dash Product", "default_code": "DASH-SKU"}
        )

        # ── Sales: one unshipped + one shipped ──────────────────────────────
        cls.env["amz.order"].create(
            {
                "backend_id": cls.backend.id,
                "amz_order_id": "ORD-OPEN",
                "amazon_status": "Unshipped",
            }
        )
        cls.env["amz.order"].create(
            {
                "backend_id": cls.backend.id,
                "amz_order_id": "ORD-DONE",
                "amazon_status": "Shipped",
            }
        )

        # ── Listings: one we win the buy box on, one we don't ───────────────
        cls.listing_us = cls.env["amz.listing"].create(
            {
                "backend_id": cls.backend.id,
                "product_id": cls.product.id,
                "seller_sku": "DASH-SKU",
                "buy_box_winner": "us",
                # Healthy margin: (30 - 4.5) / 30 = 85% > 50% target.
                "fee_basis_price": 30.0,
                "referral_fee": 4.5,
            }
        )
        cls.listing_comp = cls.env["amz.listing"].create(
            {
                "backend_id": cls.backend.id,
                "product_id": cls.product.id,
                "seller_sku": "DASH-SKU-2",
                "buy_box_winner": "competitor",
                # Thin margin: (20 - 12) / 20 = 40% < 50% target -> below.
                "fee_basis_price": 20.0,
                "referral_fee": 12.0,
            }
        )

        # ── Pricing history + competitor offers (default date = now, in 7d) ──
        cls.env["amz.price.history"].create(
            {"listing_id": cls.listing_us.id, "old_price": 10.0, "new_price": 9.0}
        )
        cls.env["amz.offer.snapshot"].create(
            {"listing_id": cls.listing_comp.id, "price": 8.0, "is_buy_box_winner": True}
        )

        # ── FBA: one SKU drifting (fulfillable - odoo = 7) ──────────────────
        cls.env["amz.fba.inventory"].create(
            {
                "backend_id": cls.backend.id,
                "seller_sku": "DASH-SKU",
                "fulfillable_qty": 10.0,
                "odoo_qty": 3.0,
            }
        )

        # ── Settlements: one matched, one variance ($5) ─────────────────────
        cls.group = cls.env["amz.settlement.group"].create(
            {"backend_id": cls.backend.id, "amazon_group_id": "GRP-1"}
        )
        cls.env["amz.settlement.reconciliation"].create(
            {"settlement_group_id": cls.group.id, "state": "matched"}
        )
        cls.env["amz.settlement.reconciliation"].create(
            {"settlement_group_id": cls.group.id, "state": "variance", "variance": 5.0}
        )

        # ── Returns: one open, one credited ─────────────────────────────────
        cls.env["amz.return"].create(
            {"backend_id": cls.backend.id, "rma_id": "RMA-OPEN", "state": "new"}
        )
        cls.env["amz.return"].create(
            {"backend_id": cls.backend.id, "rma_id": "RMA-DONE", "state": "credited"}
        )

    def _dash(self, backend=None):
        return self.env["amz.dashboard"].create(
            {"backend_id": backend.id if backend else False}
        )

    def test_kpis_all_backends(self):
        d = self._dash()
        self.assertEqual(d.orders_total, 2)
        self.assertEqual(d.orders_unshipped, 1)
        self.assertEqual(d.listings_total, 2)
        self.assertEqual(d.listings_buybox_us, 1)
        # One won of two with a winner → 0.5 (rendered 50% by the view widget).
        self.assertEqual(d.buybox_win_rate, 0.5)
        self.assertEqual(d.price_changes_7d, 1)
        self.assertEqual(d.offers_7d, 1)
        # Margins: 85% and 40% -> avg 62.5%, one below the 50% target.
        self.assertAlmostEqual(d.avg_margin, 0.625)
        self.assertEqual(d.listings_below_margin, 1)
        self.assertEqual(d.fba_skus, 1)
        self.assertEqual(d.fba_drift_skus, 1)
        self.assertEqual(d.fba_total_drift, 7.0)
        self.assertEqual(d.settlement_groups, 1)
        self.assertEqual(d.recon_matched, 1)
        self.assertEqual(d.recon_variance, 1)
        self.assertEqual(d.recon_variance_amount, 5.0)
        self.assertEqual(d.returns_open, 1)
        self.assertEqual(d.returns_credited, 1)

    def test_sync_timestamps_and_health(self):
        d = self._dash()
        self.assertEqual(str(d.last_order_sync), "2026-05-20 00:00:00")
        self.assertEqual(str(d.last_fba_sync), "2026-05-21 00:00:00")
        # Variance + drift present → needs attention.
        self.assertEqual(d.health_status, "attention")

    def test_backend_filter_scopes_counts(self):
        d = self._dash(self.other)
        self.assertEqual(d.orders_total, 0)
        self.assertEqual(d.listings_total, 0)
        self.assertEqual(d.fba_skus, 0)
        self.assertEqual(d.recon_variance, 0)
        self.assertEqual(d.returns_open, 0)

    def test_drilldown_actions(self):
        d = self._dash(self.backend)
        unshipped = d.action_open_unshipped()
        self.assertEqual(unshipped["res_model"], "amz.order")
        self.assertIn(("backend_id", "in", self.backend.ids), unshipped["domain"])

        drift = d.action_open_fba_drift()
        self.assertEqual(drift["res_model"], "amz.fba.inventory")
        self.assertIn(("drift", "!=", 0), drift["domain"])

        variance = d.action_open_recon_variance()
        self.assertEqual(variance["res_model"], "amz.settlement.reconciliation")
        self.assertIn(("state", "=", "variance"), variance["domain"])

        returns = d.action_open_returns_open()
        self.assertEqual(returns["res_model"], "amz.return")

        jobs = d.action_open_failed_jobs()
        self.assertEqual(jobs["res_model"], "queue.job")
        # queue.job is server-wide: no backend scoping on the drill-down.
        self.assertNotIn(("backend_id", "in", self.backend.ids), jobs["domain"])

    def test_drilldown_below_margin_and_price_changes(self):
        d = self._dash(self.backend)
        below = d.action_open_below_margin()
        self.assertEqual(below["res_model"], "amz.listing")
        self.assertIn(("below_target_margin", "=", True), below["domain"])
        self.assertIn(("backend_id", "in", self.backend.ids), below["domain"])

        prices = d.action_open_price_changes()
        self.assertEqual(prices["res_model"], "amz.price.history")
        self.assertIn(("backend_id", "in", self.backend.ids), prices["domain"])

    def test_health_ok_for_clean_backend(self):
        """A backend with no failed jobs, variances, drift, or below-margin
        listings reports health 'ok' — the complement of the seeded backend."""
        d = self._dash(self.other)
        self.assertEqual(d.recon_variance, 0)
        self.assertEqual(d.fba_drift_skus, 0)
        self.assertEqual(d.listings_below_margin, 0)
        self.assertEqual(d.health_status, "ok")
        # Zero-denominator / empty-list guards on the empty backend.
        self.assertEqual(d.buybox_win_rate, 0.0)
        self.assertEqual(d.avg_margin, 0.0)

    def test_fba_total_drift_uses_absolute_value(self):
        """A SKU where Odoo on-hand exceeds Amazon's fulfillable qty contributes
        its absolute drift to the total (not a negative offset)."""
        # Existing seeded SKU drifts +7 (10 - 3). Add one drifting -4 (2 - 6).
        self.env["amz.fba.inventory"].create(
            {
                "backend_id": self.backend.id,
                "seller_sku": "DASH-SKU-NEG",
                "fulfillable_qty": 2.0,
                "odoo_qty": 6.0,
            }
        )
        d = self._dash(self.backend)
        self.assertEqual(d.fba_drift_skus, 2)
        # abs(+7) + abs(-4) = 11, not 7 - 4 = 3.
        self.assertAlmostEqual(d.fba_total_drift, 11.0)
