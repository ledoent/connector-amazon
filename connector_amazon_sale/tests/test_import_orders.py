from unittest.mock import MagicMock, patch

from odoo.tests.common import TransactionCase
from odoo.tools import mute_logger

from odoo.addons.connector_amazon.tests.common import (
    SANDBOX_GET_ORDER_ADDRESS_PAYLOAD,
    SANDBOX_GET_ORDER_ITEMS_PAYLOAD,
    SANDBOX_GET_ORDERS_PAYLOAD,
)

try:
    from sp_api.base import SellingApiException
except ImportError:
    SellingApiException = Exception

AMZ_ORDER_ID = "902-1845936-5435065"


class TestImportOrders(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.backend = cls.env["amz.backend"].create(
            {
                "name": "Test Sale Backend",
                "client_id": "test_client_id",
                "client_secret": "test_secret",
                "refresh_token": "test_token",
                "marketplace_id": "ATVPDKIKX0DER",
                "sandbox": True,
                "warehouse_id": cls.env["stock.warehouse"].search([], limit=1).id,
            }
        )

    def _mock_orders_api(self, mock_api_class):
        api_instance = MagicMock()
        mock_api_class.return_value = api_instance

        orders_response = MagicMock()
        orders_response.payload = SANDBOX_GET_ORDERS_PAYLOAD
        api_instance.get_orders.return_value = orders_response

        items_response = MagicMock()
        items_response.payload = SANDBOX_GET_ORDER_ITEMS_PAYLOAD
        api_instance.get_order_items.return_value = items_response

        address_response = MagicMock()
        address_response.payload = SANDBOX_GET_ORDER_ADDRESS_PAYLOAD
        api_instance.get_order_address.return_value = address_response

        return api_instance

    @patch("sp_api.api.Orders")
    def test_import_orders_enqueues_jobs(self, mock_orders_class):
        self._mock_orders_api(mock_orders_class)
        with patch.object(type(self.backend), "with_delay") as mock_delay:
            delayed = MagicMock()
            mock_delay.return_value = delayed
            self.backend.import_orders()

        # 2 orders in sandbox payload, both Unshipped (not filtered)
        self.assertEqual(mock_delay.call_count, 2)
        job_calls = [c[0][0] for c in delayed._import_order.call_args_list]
        self.assertIn("902-1845936-5435065", job_calls)
        self.assertIn("902-8745147-1934268", job_calls)

    @patch("sp_api.api.Orders")
    def test_import_orders_updates_cursor(self, mock_orders_class):
        self._mock_orders_api(mock_orders_class)
        self.backend.last_import_date = False
        with patch.object(type(self.backend), "with_delay", return_value=MagicMock()):
            self.backend.import_orders()
        self.assertTrue(self.backend.last_import_date)

    @patch("sp_api.api.Orders")
    def test_import_order_creates_amz_order(self, mock_orders_class):
        self._mock_orders_api(mock_orders_class)
        with mute_logger("odoo.addons.connector_amazon_sale.models.sale_order"):
            self.backend._import_order(AMZ_ORDER_ID)

        amz_order = self.env["amz.order"].search(
            [
                ("backend_id", "=", self.backend.id),
                ("amz_order_id", "=", AMZ_ORDER_ID),
            ]
        )
        self.assertEqual(len(amz_order), 1)
        self.assertTrue(amz_order.sale_order_id)

    @patch("sp_api.api.Orders")
    def test_import_order_idempotent(self, mock_orders_class):
        self._mock_orders_api(mock_orders_class)
        with mute_logger("odoo.addons.connector_amazon_sale.models.sale_order"):
            self.backend._import_order(AMZ_ORDER_ID)
            self.backend._import_order(AMZ_ORDER_ID)

        amz_orders = self.env["amz.order"].search(
            [
                ("backend_id", "=", self.backend.id),
                ("amz_order_id", "=", AMZ_ORDER_ID),
            ]
        )
        self.assertEqual(
            len(amz_orders), 1, "Re-import must not create duplicate amz.order"
        )

    @patch("sp_api.api.Orders")
    def test_import_order_creates_order_lines(self, mock_orders_class):
        self._mock_orders_api(mock_orders_class)
        with mute_logger("odoo.addons.connector_amazon_sale.models.sale_order"):
            self.backend._import_order(AMZ_ORDER_ID)

        amz_order = self.env["amz.order"].search(
            [
                ("backend_id", "=", self.backend.id),
                ("amz_order_id", "=", AMZ_ORDER_ID),
            ]
        )
        self.assertEqual(len(amz_order.amz_order_line_ids), 1)
        line = amz_order.amz_order_line_ids[0]
        self.assertEqual(line.asin, "B00551Q3CS")
        self.assertEqual(line.seller_sku, "NABetaASINB00551Q3CS")
        self.assertEqual(line.quantity_ordered, 1)

    @patch("sp_api.api.Orders")
    def test_import_order_creates_partner(self, mock_orders_class):
        self._mock_orders_api(mock_orders_class)
        with mute_logger("odoo.addons.connector_amazon_sale.models.sale_order"):
            self.backend._import_order(AMZ_ORDER_ID)

        amz_order = self.env["amz.order"].search(
            [
                ("backend_id", "=", self.backend.id),
                ("amz_order_id", "=", AMZ_ORDER_ID),
            ]
        )
        partner = amz_order.sale_order_id.partner_id
        self.assertEqual(partner.city, "SEATTLE")
        self.assertEqual(partner.country_id.code, "US")

    @patch("sp_api.api.Orders")
    def test_import_order_without_matching_product(self, mock_orders_class):
        """Order lines without a matching SKU are created as description-only lines."""
        self._mock_orders_api(mock_orders_class)
        with mute_logger("odoo.addons.connector_amazon_sale.models.sale_order"):
            self.backend._import_order(AMZ_ORDER_ID)

        amz_order = self.env["amz.order"].search(
            [
                ("backend_id", "=", self.backend.id),
                ("amz_order_id", "=", AMZ_ORDER_ID),
            ]
        )
        sale_line = amz_order.sale_order_id.order_line[0]
        self.assertFalse(
            sale_line.product_id,
            "SKU with no matching product must still create a sale.order.line",
        )

    @patch("sp_api.api.Orders")
    def test_import_order_api_error_skips_gracefully(self, mock_orders_class):
        """SellingApiException from get_order_items must be logged and swallowed."""
        api_instance = MagicMock()
        mock_orders_class.return_value = api_instance
        api_instance.get_order_items.side_effect = SellingApiException(
            [{"code": "InvalidInput", "message": "Could not match input arguments"}],
            headers={},
        )

        with mute_logger("odoo.addons.connector_amazon_sale.models.amz_backend"):
            self.backend._import_order("902-SANDBOX-TEST")

        amz_order = self.env["amz.order"].search(
            [
                ("backend_id", "=", self.backend.id),
                ("amz_order_id", "=", "902-SANDBOX-TEST"),
            ]
        )
        self.assertFalse(amz_order, "No amz.order must be created when API call fails")

    @patch("sp_api.api.Orders")
    def test_import_orders_sandbox_uses_test_case_key(self, mock_orders_class):
        """Sandbox mode must call get_orders with CreatedAfter=TEST_CASE_200."""
        api_instance = MagicMock()
        mock_orders_class.return_value = api_instance
        response = MagicMock()
        response.payload = {"Orders": []}
        api_instance.get_orders.return_value = response

        self.backend.sandbox = True
        with patch.object(type(self.backend), "with_delay", return_value=MagicMock()):
            self.backend.import_orders()

        call_kwargs = api_instance.get_orders.call_args.kwargs
        self.assertEqual(call_kwargs.get("CreatedAfter"), "TEST_CASE_200")
        self.assertNotIn("LastUpdatedAfter", call_kwargs)

    # ── Phase 2: opt-in auto-invoice ──────────────────────────────────────────

    def _setup_invoiceable_product(self):
        income = self.env["account.account"].create(
            {"name": "Amz Income", "code": "ZIN100", "account_type": "income"}
        )
        if not self.env["account.journal"].search(
            [("type", "=", "sale"), ("company_id", "=", self.env.company.id)], limit=1
        ):
            self.env["account.journal"].create(
                {"name": "Sales", "type": "sale", "code": "ZSJ"}
            )
        product = self.env["product.product"].create(
            {
                "name": "Amazon Card Book",
                "default_code": "NABetaASINB00551Q3CS",
                "invoice_policy": "order",
                "list_price": 25.0,
            }
        )
        product.property_account_income_id = income
        return product

    @patch("sp_api.api.Orders")
    def test_import_order_auto_invoice_on(self, mock_orders_class):
        """amazon_auto_invoice=True → SO is confirmed and a posted invoice exists."""
        self._mock_orders_api(mock_orders_class)
        self._setup_invoiceable_product()
        self.backend.amazon_auto_invoice = True

        with mute_logger("odoo.addons.connector_amazon_sale.models.sale_order"):
            self.backend._import_order(AMZ_ORDER_ID)

        amz_order = self.env["amz.order"].search(
            [("backend_id", "=", self.backend.id), ("amz_order_id", "=", AMZ_ORDER_ID)]
        )
        invoices = amz_order.sale_order_id.invoice_ids
        self.assertTrue(invoices, "auto-invoice must create an invoice")
        self.assertEqual(invoices[0].state, "posted")
        self.assertEqual(invoices[0].move_type, "out_invoice")

    @patch("sp_api.api.Orders")
    def test_import_order_auto_invoice_off(self, mock_orders_class):
        """Default (toggle off) → sale order only, no invoice."""
        self._mock_orders_api(mock_orders_class)
        self._setup_invoiceable_product()
        self.assertFalse(self.backend.amazon_auto_invoice)

        with mute_logger("odoo.addons.connector_amazon_sale.models.sale_order"):
            self.backend._import_order(AMZ_ORDER_ID)

        amz_order = self.env["amz.order"].search(
            [("backend_id", "=", self.backend.id), ("amz_order_id", "=", AMZ_ORDER_ID)]
        )
        self.assertFalse(amz_order.sale_order_id.invoice_ids)

    @patch("sp_api.api.Orders")
    def test_import_order_auto_invoice_failure_non_fatal(self, mock_orders_class):
        """A billing failure must be swallowed — the order still imports."""
        self._mock_orders_api(mock_orders_class)
        self._setup_invoiceable_product()
        self.backend.amazon_auto_invoice = True

        def boom(self_inner, *a, **kw):
            raise ValueError("billing exploded")

        with (
            patch.object(
                type(self.env["sale.order"]),
                "_amazon_create_and_post_invoice",
                boom,
            ),
            mute_logger("odoo.addons.connector_amazon_sale.models.amz_backend"),
        ):
            self.backend._import_order(AMZ_ORDER_ID)

        amz_order = self.env["amz.order"].search(
            [("backend_id", "=", self.backend.id), ("amz_order_id", "=", AMZ_ORDER_ID)]
        )
        self.assertTrue(amz_order, "order import must survive an auto-invoice failure")
        self.assertTrue(amz_order.sale_order_id)
