from unittest.mock import MagicMock, patch

from odoo.exceptions import UserError, ValidationError
from odoo.tests.common import TransactionCase
from odoo.tools import mute_logger

AMZ_SKU = "NABetaASINB00551Q3CS"
AMZ_ASIN = "B00551Q3CS"


class TestInventory(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.warehouse = cls.env["stock.warehouse"].search([], limit=1)
        cls.backend = cls.env["amz.backend"].create(
            {
                "name": "Test Inventory Backend",
                "client_id": "test_client_id",
                "client_secret": "test_secret",
                "refresh_token": "test_token",
                "marketplace_id": "ATVPDKIKX0DER",
                "sandbox": True,
                "warehouse_id": cls.warehouse.id,
                "seller_id": "TEST_SELLER_ID",
                "inventory_sync_enabled": True,
                "inventory_expose_ratio": 1.0,
                "inventory_min_reserve": 0,
            }
        )
        cls.product = cls.env["product.product"].create(
            {
                "name": "FBM Test Product",
                "default_code": AMZ_SKU,
                "type": "consu",
                "is_storable": True,
            }
        )
        cls.listing = cls.env["amz.listing"].create(
            {
                "backend_id": cls.backend.id,
                "product_id": cls.product.id,
                "seller_sku": AMZ_SKU,
                "asin": AMZ_ASIN,
                "inventory_sync_enabled": True,
            }
        )
        cls.stock_location = cls.warehouse.lot_stock_id

    def _create_quant(self, qty, reserved=0.0, location=None):
        """Create a stock.quant with given on-hand and reserved quantities."""
        loc = location or self.stock_location
        return self.env["stock.quant"].create(
            {
                "product_id": self.product.id,
                "location_id": loc.id,
                "quantity": float(qty),
                "reserved_quantity": float(reserved),
            }
        )

    def _clear_quants(self):
        self.env["stock.quant"].search([("product_id", "=", self.product.id)]).unlink()

    # ── _compute_amazon_qty ──────────────────────────────────────────────────

    def test_compute_qty_basic(self):
        self._clear_quants()
        self._create_quant(100, reserved=20)
        qty = self.backend._compute_amazon_qty(self.product)
        self.assertEqual(qty, 80)

    def test_compute_qty_applies_expose_ratio(self):
        self._clear_quants()
        self._create_quant(100)
        self.backend.inventory_expose_ratio = 0.5
        qty = self.backend._compute_amazon_qty(self.product)
        self.assertEqual(qty, 50)
        self.backend.inventory_expose_ratio = 1.0

    def test_compute_qty_applies_min_reserve(self):
        self._clear_quants()
        self._create_quant(100)
        self.backend.inventory_expose_ratio = 0.5
        self.backend.inventory_min_reserve = 10
        qty = self.backend._compute_amazon_qty(self.product)
        self.assertEqual(qty, 40)
        self.backend.inventory_expose_ratio = 1.0
        self.backend.inventory_min_reserve = 0

    def test_compute_qty_never_negative(self):
        self._clear_quants()
        self._create_quant(5)
        self.backend.inventory_min_reserve = 20
        qty = self.backend._compute_amazon_qty(self.product)
        self.assertEqual(qty, 0)
        self.backend.inventory_min_reserve = 0

    def test_compute_qty_uses_specific_locations(self):
        self._clear_quants()
        other_location = self.env["stock.location"].create(
            {
                "name": "Other FBM Loc",
                "usage": "internal",
                "location_id": self.warehouse.view_location_id.id,
            }
        )
        self._create_quant(100, location=self.stock_location)
        self._create_quant(30, location=other_location)
        self.backend.inventory_location_ids = other_location
        qty = self.backend._compute_amazon_qty(self.product)
        self.assertEqual(qty, 30)
        self.backend.inventory_location_ids = False

    def test_compute_qty_uses_warehouse_default_when_no_locations(self):
        self._clear_quants()
        self._create_quant(60, location=self.stock_location)
        self.backend.inventory_location_ids = False
        qty = self.backend._compute_amazon_qty(self.product)
        self.assertEqual(qty, 60)

    # ── _push_inventory ──────────────────────────────────────────────────────

    @patch("sp_api.api.ListingsItems")
    def test_push_inventory_calls_api_with_correct_qty(self, mock_listings_class):
        api_instance = MagicMock()
        mock_listings_class.return_value = api_instance
        self._clear_quants()
        self._create_quant(50)
        self.listing.last_pushed_qty = -1

        self.backend._push_inventory()

        self.assertTrue(api_instance.patch_listings_item.called)
        call_kwargs = api_instance.patch_listings_item.call_args.kwargs
        self.assertEqual(call_kwargs["sellerId"], "TEST_SELLER_ID")
        self.assertEqual(call_kwargs["sku"], AMZ_SKU)
        patches = call_kwargs["body"]["patches"]
        fav = patches[0]["value"][0]
        self.assertEqual(fav["fulfillment_channel_code"], "DEFAULT")
        self.assertEqual(fav["quantity"], 50)

    @patch("sp_api.api.ListingsItems")
    def test_push_inventory_skips_when_qty_unchanged(self, mock_listings_class):
        api_instance = MagicMock()
        mock_listings_class.return_value = api_instance
        self._clear_quants()
        self._create_quant(50)
        self.listing.last_pushed_qty = 50

        self.backend._push_inventory()

        api_instance.patch_listings_item.assert_not_called()

    @patch("sp_api.api.ListingsItems")
    def test_push_inventory_respects_per_listing_flag(self, mock_listings_class):
        api_instance = MagicMock()
        mock_listings_class.return_value = api_instance
        self._clear_quants()
        self._create_quant(50)
        self.listing.inventory_sync_enabled = False
        self.listing.last_pushed_qty = -1

        self.backend._push_inventory()

        api_instance.patch_listings_item.assert_not_called()
        self.listing.inventory_sync_enabled = True

    @patch("sp_api.api.ListingsItems")
    def test_push_inventory_updates_last_pushed_qty(self, mock_listings_class):
        api_instance = MagicMock()
        mock_listings_class.return_value = api_instance
        self._clear_quants()
        self._create_quant(75)
        self.listing.last_pushed_qty = -1
        self.assertFalse(self.listing.last_inventory_push_date)

        self.backend._push_inventory()

        self.assertEqual(self.listing.last_pushed_qty, 75)
        self.assertTrue(self.listing.last_inventory_push_date)

    @patch("sp_api.api.ListingsItems")
    def test_push_inventory_api_error_isolates_listings(self, mock_listings_class):
        """An API failure for one listing must not abort the remaining listings."""
        api_instance = MagicMock()
        mock_listings_class.return_value = api_instance

        product2 = self.env["product.product"].create(
            {
                "name": "FBM Test Product 2",
                "default_code": "SKU_2",
                "type": "consu",
                "is_storable": True,
            }
        )
        listing2 = self.env["amz.listing"].create(
            {
                "backend_id": self.backend.id,
                "product_id": product2.id,
                "seller_sku": "SKU_2",
                "inventory_sync_enabled": True,
            }
        )
        self._clear_quants()
        self._create_quant(30)
        self.env["stock.quant"].create(
            {
                "product_id": product2.id,
                "location_id": self.stock_location.id,
                "quantity": 20.0,
            }
        )
        self.listing.last_pushed_qty = -1
        listing2.last_pushed_qty = -1
        api_instance.patch_listings_item.side_effect = [Exception("API down"), None]

        with mute_logger("odoo.addons.connector_amazon_inventory.models.amz_backend"):
            self.backend._push_inventory()

        self.assertEqual(api_instance.patch_listings_item.call_count, 2)
        self.assertEqual(self.listing.last_pushed_qty, -1)
        self.assertEqual(listing2.last_pushed_qty, 20)

    def test_push_inventory_backend_flag_disables_cron(self):
        """push_inventory() cron skips backends with inventory_sync_enabled=False."""
        self.backend.inventory_sync_enabled = False
        try:
            with patch.object(type(self.backend), "with_delay") as mock_delay:
                self.backend.push_inventory()
                mock_delay.assert_not_called()
        finally:
            self.backend.inventory_sync_enabled = True

    @patch("sp_api.api.ListingsItems")
    def test_push_inventory_zero_qty_fires_when_previously_nonzero(
        self, mock_listings_class
    ):
        """Going from in-stock to 0 must push (Amazon needs to know)."""
        api_instance = MagicMock()
        mock_listings_class.return_value = api_instance
        self._clear_quants()
        self.listing.last_pushed_qty = 10

        self.backend._push_inventory()

        self.assertTrue(api_instance.patch_listings_item.called)
        qty_sent = api_instance.patch_listings_item.call_args.kwargs["body"]["patches"][
            0
        ]["value"][0]["quantity"]
        self.assertEqual(qty_sent, 0)

    # ── _compute_amazon_qty edge cases ───────────────────────────────────────

    def test_compute_qty_floors_non_integer_result(self):
        """An odd free qty × ratio is floored to a whole unit (50.5 → 50)."""
        self._clear_quants()
        self._create_quant(101)
        self.backend.inventory_expose_ratio = 0.5
        qty = self.backend._compute_amazon_qty(self.product)
        self.assertEqual(qty, 50)
        self.backend.inventory_expose_ratio = 1.0

    def test_compute_qty_nets_reserved_across_multiple_quants(self):
        """free_qty sums per-quant max(0, on_hand - reserved) over all quants."""
        self._clear_quants()
        self._create_quant(40, reserved=10)  # contributes 30
        self._create_quant(25, reserved=5)  # contributes 20
        qty = self.backend._compute_amazon_qty(self.product)
        self.assertEqual(qty, 50)

    def test_compute_qty_clamps_per_quant_when_reserved_exceeds_on_hand(self):
        """A quant with reserved > on_hand contributes 0, not a negative number."""
        self._clear_quants()
        self._create_quant(10, reserved=15)  # contributes 0, not -5
        self._create_quant(30, reserved=0)  # contributes 30
        qty = self.backend._compute_amazon_qty(self.product)
        self.assertEqual(qty, 30)

    # ── @api.constrains validators ───────────────────────────────────────────

    def test_expose_ratio_above_one_is_rejected(self):
        with self.assertRaises(ValidationError):
            self.backend.inventory_expose_ratio = 1.5

    def test_expose_ratio_below_zero_is_rejected(self):
        with self.assertRaises(ValidationError):
            self.backend.inventory_expose_ratio = -0.1

    def test_negative_min_reserve_is_rejected(self):
        with self.assertRaises(ValidationError):
            self.backend.inventory_min_reserve = -1

    # ── action_push_inventory / push_inventory (cron) ────────────────────────

    def test_action_push_inventory_requires_seller_id(self):
        self.backend.seller_id = False
        with self.assertRaises(UserError):
            self.backend.action_push_inventory()

    def test_action_push_inventory_enqueues_job(self):
        with patch.object(type(self.backend), "with_delay") as mock_delay:
            self.backend.action_push_inventory()
            mock_delay.assert_called_once()

    def test_push_inventory_cron_enqueues_for_enabled_backend(self):
        """The cron enqueues a push job for a backend with sync enabled."""
        with patch.object(type(self.backend), "with_delay") as mock_delay:
            self.backend.push_inventory()
            mock_delay.assert_called_once()
