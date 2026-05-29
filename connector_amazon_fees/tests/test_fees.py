from unittest.mock import MagicMock, patch

from odoo.tests.common import TransactionCase

FEE_PAYLOAD = {
    "FeesEstimateResult": {
        "Status": "Success",
        "FeesEstimate": {
            "FeeDetailList": [
                {"FeeType": "ReferralFee", "FeeAmount": {"Amount": 4.5}},
                {"FeeType": "FBAFees", "FeeAmount": {"Amount": 3.0}},
            ]
        },
    }
}


class TestFees(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.warehouse = cls.env["stock.warehouse"].search([], limit=1)
        cls.backend = cls.env["amz.backend"].create(
            {
                "name": "Fees Backend",
                "client_id": "cid",
                "client_secret": "csec",
                "refresh_token": "rtok",
                "marketplace_id": "ATVPDKIKX0DER",
                "sandbox": True,
                "warehouse_id": cls.warehouse.id,
                "seller_id": "A1SELLER",
                "pricing_mode": "competitive",
                "competitive_rule": "match_buy_box",
                "competitive_floor_margin_pct": 20.0,
            }
        )
        cls.product = cls.env["product.product"].create(
            {"name": "Fee Widget", "default_code": "FEE-SKU", "standard_price": 10.0}
        )
        cls.listing = cls.env["amz.listing"].create(
            {
                "backend_id": cls.backend.id,
                "product_id": cls.product.id,
                "seller_sku": "FEE-SKU",
                "asin": "B00FEE001",
                "current_list_price": 30.0,
                "buy_box_price": 15.0,
                "is_fba": True,
            }
        )

    def _mock_sync(self):
        with patch("sp_api.api.ProductFees") as mock_pf:
            api = MagicMock()
            mock_pf.return_value = api
            resp = MagicMock()
            resp.payload = FEE_PAYLOAD
            api.get_product_fees_estimate_for_sku.return_value = resp
            updated = self.backend._sync_fees()
        self.listing.invalidate_recordset()
        return updated, api

    def test_sync_stores_fee_breakdown(self):
        updated, api = self._mock_sync()
        self.assertEqual(updated, 1)
        # Estimate requested at the current list price, FBA flag forwarded.
        _args, kwargs = api.get_product_fees_estimate_for_sku.call_args
        self.assertEqual(kwargs["is_amazon_fulfilled"], True)
        self.assertEqual(self.listing.referral_fee, 4.5)
        self.assertEqual(self.listing.fulfillment_fee, 3.0)
        self.assertEqual(self.listing.fee_basis_price, 30.0)
        self.assertTrue(self.backend.last_fee_sync_date)

    def test_margin_math(self):
        self._mock_sync()
        self.assertEqual(self.listing.total_fees, 7.5)
        self.assertAlmostEqual(self.listing.referral_fee_pct, 0.15)
        self.assertEqual(self.listing.est_net_proceeds, 22.5)  # 30 - 7.5
        self.assertEqual(self.listing.est_net_margin, 12.5)  # 22.5 - 10 cost
        self.assertAlmostEqual(self.listing.est_margin_pct, 12.5 / 30.0)
        # 41% margin is comfortably above the 20% target.
        self.assertFalse(self.listing.below_target_margin)

    def test_fee_aware_floor_raises_above_cost_only(self):
        self._mock_sync()
        # cost-only floor = 10 * 1.2 = 12; buy box = 15 -> super() returns 15.
        # fee-aware floor = (10 + 3) / (1 - 0.15 - 0.20) = 13 / 0.65 = 20.
        target = self.backend._compute_competitive_price(self.listing)
        self.assertAlmostEqual(target, 20.0)

    def test_below_target_flag_trips_when_margin_thin(self):
        self.backend.competitive_floor_margin_pct = 50.0  # demand 50% net margin
        self._mock_sync()
        # 41% < 50% -> flagged.
        self.assertTrue(self.listing.below_target_margin)

    def test_unrecognized_fee_types_still_counted(self):
        """A fee type beyond the named ones lands in other_fees and the total."""
        payload = {
            "FeesEstimateResult": {
                "Status": "Success",
                "FeesEstimate": {
                    "FeeDetailList": [
                        {"FeeType": "ReferralFee", "FeeAmount": {"Amount": 4.5}},
                        {"FeeType": "PerItemFee", "FeeAmount": {"Amount": 0.99}},
                    ]
                },
            }
        }
        vals = self.backend._parse_fee_estimate(payload, 30.0)
        self.assertEqual(vals["other_fees"], 0.99)
        self.listing.write(vals)
        self.assertEqual(self.listing.total_fees, 5.49)  # 4.5 + 0 + 0 + 0.99

    def test_unsuccessful_status_writes_nothing(self):
        payload = {"FeesEstimateResult": {"Status": "ClientError"}}
        self.assertEqual(self.backend._parse_fee_estimate(payload, 30.0), {})

    def test_listing_without_price_is_skipped(self):
        no_price = self.env["amz.listing"].create(
            {
                "backend_id": self.backend.id,
                "product_id": self.product.id,
                "seller_sku": "FEE-SKU-NOPRICE",
            }
        )
        updated, _api = self._mock_sync()
        no_price.invalidate_recordset()
        # Only the priced listing is updated; the price-less one is left alone.
        self.assertEqual(updated, 1)
        self.assertEqual(no_price.fee_basis_price, 0.0)
        self.assertFalse(no_price.last_fee_sync_date)
