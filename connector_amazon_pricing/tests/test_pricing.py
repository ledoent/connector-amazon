from unittest.mock import MagicMock, patch

from odoo.tests.common import TransactionCase

from odoo.addons.connector_amazon.tests.common import (
    SANDBOX_GET_ORDER_ADDRESS_PAYLOAD,
    SANDBOX_GET_ORDER_ITEMS_PAYLOAD,
)

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

        self.backend.action_import_listings()

        listing = self.env["amz.listing"].search(
            [("backend_id", "=", self.backend.id), ("seller_sku", "=", "NO_MATCH_SKU")]
        )
        self.assertFalse(listing)

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
        price_val = patches[0]["value"][0]["our_price"][0]["schedule"][0]["value_with_tax"]
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
            {"backend_id": self.backend.id, "product_id": self.product.id, "seller_sku": AMZ_SKU}
        )
        listing2 = self.env["amz.listing"].create(
            {"backend_id": self.backend.id, "product_id": product2.id, "seller_sku": "SKU_SECOND"}
        )
        api_instance.patch_listings_item.side_effect = [Exception("API down"), None]

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
            self.backend._import_order(AMZ_ORDER_ID)

            listing = self.env["amz.listing"].search(
                [("backend_id", "=", self.backend.id), ("seller_sku", "=", AMZ_SKU)]
            )
            self.assertFalse(listing)
        finally:
            self.product.default_code = AMZ_SKU
