from unittest.mock import MagicMock, patch

from odoo.tests.common import TransactionCase
from odoo.tools import mute_logger

from odoo.addons.connector_amazon.tests.common import (
    SANDBOX_GET_ORDER_ADDRESS_PAYLOAD,
    SANDBOX_GET_ORDER_ITEMS_PAYLOAD,
)

try:
    from sp_api.base import SellingApiException
except ImportError:
    SellingApiException = Exception

AMZ_ORDER_ID = "902-1845936-5435065"
AMZ_SKU = "NABetaASINB00551Q3CS"
AMZ_ASIN = "B00551Q3CS"

SANDBOX_LISTINGS_PAYLOAD = {
    "numberOfResults": 1,
    "items": [
        {
            "sku": AMZ_SKU,
            "summaries": [
                {
                    "marketplaceId": "ATVPDKIKX0DER",
                    "asin": AMZ_ASIN,
                    "status": ["BUYABLE"],
                }
            ],
        }
    ],
    "pagination": {},
}


class TestPricing(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.backend = cls.env["amz.backend"].create(
            {
                "name": "Test Pricing Backend",
                "client_id": "test_client_id",
                "client_secret": "test_secret",
                "refresh_token": "test_token",
                "marketplace_id": "ATVPDKIKX0DER",
                "sandbox": True,
                "warehouse_id": cls.env["stock.warehouse"].search([], limit=1).id,
                "seller_id": "TEST_SELLER_ID",
                "pricing_mode": "pricelist",
            }
        )
        cls.product = cls.env["product.product"].create(
            {
                "name": "Test Product",
                "default_code": AMZ_SKU,
                "list_price": 25.00,
            }
        )
        cls.pricelist = cls.env["product.pricelist"].create(
            {
                "name": "Amazon US Pricelist",
                "currency_id": cls.env.ref("base.USD").id,
            }
        )
        cls.env["product.pricelist.item"].create(
            {
                "pricelist_id": cls.pricelist.id,
                "compute_price": "fixed",
                "fixed_price": 29.99,
                "product_id": cls.product.id,
            }
        )
        cls.backend.pricelist_id = cls.pricelist

    # ── amz.listing._upsert ──────────────────────────────────────────────────

    def test_upsert_creates_new_listing(self):
        listing = self.env["amz.listing"]._upsert(
            self.backend, self.product, AMZ_SKU, AMZ_ASIN
        )
        self.assertEqual(listing.seller_sku, AMZ_SKU)
        self.assertEqual(listing.asin, AMZ_ASIN)
        self.assertEqual(listing.product_id, self.product)
        self.assertEqual(listing.backend_id, self.backend)

    def test_upsert_is_idempotent(self):
        listing1 = self.env["amz.listing"]._upsert(
            self.backend, self.product, AMZ_SKU, AMZ_ASIN
        )
        listing2 = self.env["amz.listing"]._upsert(
            self.backend, self.product, AMZ_SKU, AMZ_ASIN
        )
        self.assertEqual(listing1.id, listing2.id)

    def test_upsert_updates_asin(self):
        listing = self.env["amz.listing"]._upsert(
            self.backend, self.product, AMZ_SKU, "OLD_ASIN"
        )
        updated = self.env["amz.listing"]._upsert(
            self.backend, self.product, AMZ_SKU, AMZ_ASIN
        )
        self.assertEqual(listing.id, updated.id)
        self.assertEqual(updated.asin, AMZ_ASIN)

    # ── action_import_listings ───────────────────────────────────────────────

    @patch("sp_api.api.ListingsItems")
    def test_import_listings_creates_records(self, mock_listings_class):
        api_instance = MagicMock()
        mock_listings_class.return_value = api_instance
        response = MagicMock()
        response.payload = SANDBOX_LISTINGS_PAYLOAD
        api_instance.search_listings_items.return_value = response

        self.backend.action_import_listings()

        listing = self.env["amz.listing"].search(
            [("backend_id", "=", self.backend.id), ("seller_sku", "=", AMZ_SKU)]
        )
        self.assertEqual(len(listing), 1)
        self.assertEqual(listing.asin, AMZ_ASIN)

    @patch("sp_api.api.ListingsItems")
    def test_import_listings_skips_unknown_skus(self, mock_listings_class):
        api_instance = MagicMock()
        mock_listings_class.return_value = api_instance
        response = MagicMock()
        response.payload = {
            "items": [{"sku": "NO_MATCH_SKU", "summaries": []}],
            "pagination": {},
        }
        api_instance.search_listings_items.return_value = response

        with mute_logger("odoo.addons.connector_amazon_pricing.models.amz_backend"):
            self.backend.action_import_listings()

        listing = self.env["amz.listing"].search(
            [("backend_id", "=", self.backend.id), ("seller_sku", "=", "NO_MATCH_SKU")]
        )
        self.assertFalse(listing)

    @patch("sp_api.api.ListingsItems")
    def test_import_listings_api_error_propagates(self, mock_listings_class):
        """SellingApiException from the API must bubble up to the caller."""
        api_instance = MagicMock()
        mock_listings_class.return_value = api_instance
        api_instance.search_listings_items.side_effect = SellingApiException(
            [{"code": "QuotaExceeded", "message": "Too many requests"}],
            headers={},
        )

        with (
            mute_logger("odoo.addons.connector_amazon_pricing.models.amz_backend"),
            self.assertRaises(SellingApiException),
        ):
            self.backend.action_import_listings()

    @patch("sp_api.api.ListingsItems")
    def test_import_listings_follows_pagination(self, mock_listings_class):
        """When the API returns a nextToken the method must fetch all pages."""
        api_instance = MagicMock()
        mock_listings_class.return_value = api_instance
        page1 = MagicMock()
        page1.payload = {
            "items": [{"sku": AMZ_SKU, "summaries": [{"asin": AMZ_ASIN}]}],
            "pagination": {"nextToken": "tok_page2"},
        }
        page2 = MagicMock()
        page2.payload = {"items": [], "pagination": {}}
        api_instance.search_listings_items.side_effect = [page1, page2]

        self.backend.action_import_listings()

        self.assertEqual(api_instance.search_listings_items.call_count, 2)
        second_call_kwargs = api_instance.search_listings_items.call_args_list[1].kwargs
        self.assertEqual(second_call_kwargs.get("pageToken"), "tok_page2")

    # ── _push_prices ─────────────────────────────────────────────────────────

    @patch("sp_api.api.ListingsItems")
    def test_push_prices_calls_api_with_pricelist_price(self, mock_listings_class):
        api_instance = MagicMock()
        mock_listings_class.return_value = api_instance

        self.env["amz.listing"].create(
            {
                "backend_id": self.backend.id,
                "product_id": self.product.id,
                "seller_sku": AMZ_SKU,
            }
        )

        self.backend._push_prices()

        self.assertTrue(api_instance.patch_listings_item.called)
        call_kwargs = api_instance.patch_listings_item.call_args.kwargs
        self.assertEqual(call_kwargs["sellerId"], "TEST_SELLER_ID")
        self.assertEqual(call_kwargs["sku"], AMZ_SKU)
        patches = call_kwargs["body"]["patches"]
        price_val = patches[0]["value"][0]["our_price"][0]["schedule"][0][
            "value_with_tax"
        ]
        self.assertAlmostEqual(price_val, 29.99, places=2)

    @patch("sp_api.api.ListingsItems")
    def test_push_prices_updates_listing_timestamp(self, mock_listings_class):
        api_instance = MagicMock()
        mock_listings_class.return_value = api_instance

        listing = self.env["amz.listing"].create(
            {
                "backend_id": self.backend.id,
                "product_id": self.product.id,
                "seller_sku": AMZ_SKU,
            }
        )
        self.assertFalse(listing.last_price_push_date)

        self.backend._push_prices()

        self.assertTrue(listing.last_price_push_date)

    @patch("sp_api.api.ListingsItems")
    def test_push_prices_api_error_continues_other_listings(self, mock_listings_class):
        """An API failure for one listing must not abort the remaining listings."""
        api_instance = MagicMock()
        mock_listings_class.return_value = api_instance

        product2 = self.env["product.product"].create(
            {"name": "Test Product 2", "default_code": "SKU_SECOND", "list_price": 9.99}
        )
        self.env["product.pricelist.item"].create(
            {
                "pricelist_id": self.pricelist.id,
                "compute_price": "fixed",
                "fixed_price": 9.99,
                "product_id": product2.id,
            }
        )
        listing1 = self.env["amz.listing"].create(
            {
                "backend_id": self.backend.id,
                "product_id": self.product.id,
                "seller_sku": AMZ_SKU,
            }
        )
        listing2 = self.env["amz.listing"].create(
            {
                "backend_id": self.backend.id,
                "product_id": product2.id,
                "seller_sku": "SKU_SECOND",
            }
        )
        api_instance.patch_listings_item.side_effect = [Exception("API down"), None]

        with mute_logger("odoo.addons.connector_amazon_pricing.models.amz_backend"):
            self.backend._push_prices()

        self.assertEqual(api_instance.patch_listings_item.call_count, 2)
        self.assertFalse(listing1.last_price_push_date)
        self.assertTrue(listing2.last_price_push_date)

    @patch("sp_api.api.ListingsItems")
    def test_push_prices_no_pricelist_skips(self, mock_listings_class):
        api_instance = MagicMock()
        mock_listings_class.return_value = api_instance

        self.env["amz.listing"].create(
            {
                "backend_id": self.backend.id,
                "product_id": self.product.id,
                "seller_sku": AMZ_SKU,
            }
        )
        self.backend.pricelist_id = False

        self.backend._push_prices()

        api_instance.patch_listings_item.assert_not_called()
        self.backend.pricelist_id = self.pricelist

    # ── _import_order auto-create ─────────────────────────────────────────────

    @patch("sp_api.api.Orders")
    def test_import_order_auto_creates_listing(self, mock_orders_class):
        api_instance = MagicMock()
        mock_orders_class.return_value = api_instance

        items_response = MagicMock()
        items_response.payload = SANDBOX_GET_ORDER_ITEMS_PAYLOAD
        api_instance.get_order_items.return_value = items_response

        address_response = MagicMock()
        address_response.payload = SANDBOX_GET_ORDER_ADDRESS_PAYLOAD
        api_instance.get_order_address.return_value = address_response

        self.backend._import_order(AMZ_ORDER_ID)

        listing = self.env["amz.listing"].search(
            [("backend_id", "=", self.backend.id), ("seller_sku", "=", AMZ_SKU)]
        )
        self.assertEqual(len(listing), 1)
        self.assertEqual(listing.asin, AMZ_ASIN)
        self.assertEqual(listing.product_id, self.product)

    @patch("sp_api.api.Orders")
    def test_import_order_no_listing_for_unknown_sku(self, mock_orders_class):
        """Order lines without a matching product don't create a listing."""
        api_instance = MagicMock()
        mock_orders_class.return_value = api_instance

        items_response = MagicMock()
        items_response.payload = SANDBOX_GET_ORDER_ITEMS_PAYLOAD
        api_instance.get_order_items.return_value = items_response

        address_response = MagicMock()
        address_response.payload = SANDBOX_GET_ORDER_ADDRESS_PAYLOAD
        api_instance.get_order_address.return_value = address_response

        # Remove the product's default_code so SKU won't match
        self.product.default_code = "SOMETHING_ELSE"
        try:
            with mute_logger("odoo.addons.connector_amazon_sale.models.sale_order"):
                self.backend._import_order(AMZ_ORDER_ID)

            listing = self.env["amz.listing"].search(
                [("backend_id", "=", self.backend.id), ("seller_sku", "=", AMZ_SKU)]
            )
            self.assertFalse(listing)
        finally:
            self.product.default_code = AMZ_SKU


SANDBOX_COMPETITIVE_PAYLOAD = [
    {
        "ASIN": AMZ_ASIN,
        "status": "Success",
        "Product": {
            "CompetitivePricing": {
                "CompetitivePrices": [
                    {
                        "CompetitivePriceId": "1",
                        "Price": {
                            "ListingPrice": {"Amount": "29.99", "CurrencyCode": "USD"},
                            "ShippingPrice": {"Amount": "0.00", "CurrencyCode": "USD"},
                        },
                        "condition": "New",
                        "belongsToRequester": False,
                    }
                ]
            }
        },
    }
]


def _mock_competitive_api(test_case, payload):
    """Return a mock ProductsV0 api pre-configured with the given payload."""
    api = MagicMock()
    resp = MagicMock()
    resp.payload = payload
    api.get_competitive_pricing_for_asins.return_value = resp
    return api


class TestCompetitivePricing(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.backend = cls.env["amz.backend"].create(
            {
                "name": "Test Competitive Backend",
                "client_id": "test_client_id",
                "client_secret": "test_secret",
                "refresh_token": "test_token",
                "marketplace_id": "ATVPDKIKX0DER",
                "sandbox": True,
                "warehouse_id": cls.env["stock.warehouse"].search([], limit=1).id,
                "seller_id": "TEST_SELLER_ID",
                "pricing_mode": "competitive",
                "competitive_rule": "match_buy_box",
                "competitive_undercut_pct": 2.0,
                "competitive_floor_margin_pct": 15.0,
                "price_push_enabled": True,
            }
        )
        cls.product = cls.env["product.product"].create(
            {
                "name": "Competitive Test Product",
                "default_code": AMZ_SKU,
                "standard_price": 10.0,
            }
        )
        cls.listing = cls.env["amz.listing"].create(
            {
                "backend_id": cls.backend.id,
                "product_id": cls.product.id,
                "seller_sku": AMZ_SKU,
                "asin": AMZ_ASIN,
            }
        )

    # ── _sync_competitive_prices ──────────────────────────────────────────────

    def test_sync_competitive_prices_updates_buy_box(self):
        api = _mock_competitive_api(self, SANDBOX_COMPETITIVE_PAYLOAD)
        with patch.object(type(self.backend), "_get_api", return_value=api):
            self.backend._sync_competitive_prices()
        self.listing.invalidate_recordset()
        self.assertAlmostEqual(self.listing.buy_box_price, 29.99)
        self.assertEqual(self.listing.buy_box_winner, "competitor")

    def test_sync_competitive_prices_updates_all_skus_sharing_asin(self):
        """Two SKUs on the same ASIN must both receive the buy-box update."""
        product2 = self.env["product.product"].create(
            {"name": "Second SKU same ASIN", "default_code": "SKU_SHARED_2"}
        )
        listing2 = self.env["amz.listing"].create(
            {
                "backend_id": self.backend.id,
                "product_id": product2.id,
                "seller_sku": "SKU_SHARED_2",
                "asin": AMZ_ASIN,
            }
        )
        api = _mock_competitive_api(self, SANDBOX_COMPETITIVE_PAYLOAD)
        with patch.object(type(self.backend), "_get_api", return_value=api):
            self.backend._sync_competitive_prices()
        # API should be asked for the ASIN only once (deduped), not per-SKU.
        asin_arg = api.get_competitive_pricing_for_asins.call_args.kwargs["asin_list"]
        self.assertEqual(asin_arg.count(AMZ_ASIN), 1)
        self.listing.invalidate_recordset()
        listing2.invalidate_recordset()
        self.assertAlmostEqual(self.listing.buy_box_price, 29.99)
        self.assertAlmostEqual(listing2.buy_box_price, 29.99)

    def test_sync_competitive_prices_marks_us_as_winner(self):
        payload = [
            {
                "ASIN": AMZ_ASIN,
                "status": "Success",
                "Product": {
                    "CompetitivePricing": {
                        "CompetitivePrices": [
                            {
                                "CompetitivePriceId": "1",
                                "Price": {
                                    "ListingPrice": {
                                        "Amount": "25.00",
                                        "CurrencyCode": "USD",
                                    }
                                },
                                "belongsToRequester": True,
                            }
                        ]
                    }
                },
            }
        ]
        api = _mock_competitive_api(self, payload)
        with patch.object(type(self.backend), "_get_api", return_value=api):
            self.backend._sync_competitive_prices()
        self.listing.invalidate_recordset()
        self.assertEqual(self.listing.buy_box_winner, "us")

    def test_sync_competitive_prices_batches_by_20(self):
        api = _mock_competitive_api(self, [])

        extra_listings = self.env["amz.listing"]
        extra_products = self.env["product.product"]
        for idx in range(21):
            prod = self.env["product.product"].create(
                {"name": f"Batch Prod {idx}", "default_code": f"BATCHSKU{idx}"}
            )
            extra_products |= prod
            lst = self.env["amz.listing"].create(
                {
                    "backend_id": self.backend.id,
                    "product_id": prod.id,
                    "seller_sku": f"BATCHSKU{idx}",
                    "asin": f"B00BATCH{idx:04d}",
                }
            )
            extra_listings |= lst

        with patch.object(type(self.backend), "_get_api", return_value=api):
            self.backend._sync_competitive_prices()

        self.assertEqual(api.get_competitive_pricing_for_asins.call_count, 2)
        extra_listings.unlink()
        extra_products.unlink()

    def test_sync_competitive_prices_skips_listing_without_asin(self):
        api = _mock_competitive_api(self, [])
        self.listing.asin = False
        try:
            with patch.object(type(self.backend), "_get_api", return_value=api):
                self.backend._sync_competitive_prices()
            api.get_competitive_pricing_for_asins.assert_not_called()
        finally:
            self.listing.asin = AMZ_ASIN

    def test_sync_competitive_prices_skips_non_success_items(self):
        """Items with status != 'Success' must not update listing."""
        payload = [{"ASIN": AMZ_ASIN, "status": "ClientError"}]
        api = _mock_competitive_api(self, payload)
        self.listing.buy_box_price = 5.0
        with patch.object(type(self.backend), "_get_api", return_value=api):
            self.backend._sync_competitive_prices()
        self.listing.invalidate_recordset()
        self.assertAlmostEqual(self.listing.buy_box_price, 5.0)

    def test_sync_competitive_prices_continues_after_batch_error(self):
        """An API error on one batch must not prevent subsequent batches."""
        api = MagicMock()
        api.get_competitive_pricing_for_asins.side_effect = [
            Exception("network error"),
            MagicMock(payload=[]),
        ]
        extra_listings = self.env["amz.listing"]
        extra_products = self.env["product.product"]
        for idx in range(21):
            prod = self.env["product.product"].create(
                {"name": f"ErrProd {idx}", "default_code": f"ERRSKU{idx}"}
            )
            extra_products |= prod
            lst = self.env["amz.listing"].create(
                {
                    "backend_id": self.backend.id,
                    "product_id": prod.id,
                    "seller_sku": f"ERRSKU{idx}",
                    "asin": f"B00ERR{idx:05d}",
                }
            )
            extra_listings |= lst
        with (
            patch.object(type(self.backend), "_get_api", return_value=api),
            mute_logger("odoo.addons.connector_amazon_pricing.models.amz_backend"),
        ):
            self.backend._sync_competitive_prices()
        self.assertEqual(api.get_competitive_pricing_for_asins.call_count, 2)
        extra_listings.unlink()
        extra_products.unlink()

    def test_sync_competitive_prices_updates_last_price_sync_date(self):
        self.backend.last_price_sync_date = False
        api = _mock_competitive_api(self, [])
        with patch.object(type(self.backend), "_get_api", return_value=api):
            self.backend._sync_competitive_prices()
        self.backend.invalidate_recordset()
        self.assertTrue(self.backend.last_price_sync_date)

    # ── _compute_competitive_price ────────────────────────────────────────────

    def test_compute_competitive_price_match_buy_box(self):
        self.backend.competitive_rule = "match_buy_box"
        self.listing.buy_box_price = 50.0
        price = self.backend._compute_competitive_price(self.listing)
        self.assertAlmostEqual(price, 50.0)

    def test_compute_competitive_price_undercut(self):
        self.backend.competitive_rule = "undercut_buy_box"
        self.backend.competitive_undercut_pct = 2.0
        self.listing.buy_box_price = 100.0
        price = self.backend._compute_competitive_price(self.listing)
        self.assertAlmostEqual(price, 98.0)

    def test_compute_competitive_price_floor_clamps(self):
        self.backend.competitive_rule = "undercut_buy_box"
        self.backend.competitive_undercut_pct = 50.0
        self.backend.competitive_floor_margin_pct = 15.0
        self.listing.buy_box_price = 10.0
        self.product.standard_price = 10.0
        price = self.backend._compute_competitive_price(self.listing)
        # undercut = 5.0, floor = 10 * 1.15 = 11.5
        self.assertAlmostEqual(price, 11.5)

    def test_compute_competitive_price_match_respects_floor(self):
        self.backend.competitive_rule = "match_buy_box"
        self.backend.competitive_floor_margin_pct = 20.0
        self.listing.buy_box_price = 9.0
        self.product.standard_price = 10.0
        price = self.backend._compute_competitive_price(self.listing)
        # buy box = 9.0 < floor = 10 * 1.20 = 12.0 → price at floor
        self.assertAlmostEqual(price, 12.0)

    def test_compute_competitive_price_returns_none_without_buy_box(self):
        self.listing.buy_box_price = 0.0
        price = self.backend._compute_competitive_price(self.listing)
        self.assertIsNone(price)

    # ── _do_sync_prices / sync ordering ──────────────────────────────────────

    def test_do_sync_prices_pulls_before_pushing(self):
        call_order = []

        def fake_pull(self_inner):
            call_order.append("pull")

        def fake_push(self_inner):
            call_order.append("push")

        with (
            patch.object(type(self.backend), "_sync_competitive_prices", fake_pull),
            patch.object(type(self.backend), "_push_prices", fake_push),
        ):
            self.backend._do_sync_prices()

        self.assertEqual(call_order, ["pull", "push"])

    def test_do_sync_prices_skips_pull_for_pricelist_mode(self):
        self.backend.pricing_mode = "pricelist"
        called_pull = []

        def fake_pull(self_inner):
            called_pull.append(True)

        with (
            patch.object(type(self.backend), "_sync_competitive_prices", fake_pull),
            patch.object(type(self.backend), "_push_prices", lambda s: None),
        ):
            self.backend._do_sync_prices()

        self.assertFalse(called_pull)
        self.backend.pricing_mode = "competitive"

    def test_sync_prices_enqueues_only_for_price_push_enabled(self):
        """sync_prices() cron must skip backends where price_push_enabled=False."""
        self.backend.price_push_enabled = False
        queued = []

        def capturing_with_delay(self_inner, **kw):
            queued.append(kw.get("description", ""))
            return MagicMock()

        with patch.object(type(self.backend), "with_delay", capturing_with_delay):
            self.backend.sync_prices()

        self.assertFalse(queued)
        self.backend.price_push_enabled = True
