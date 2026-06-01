from unittest.mock import MagicMock, patch

from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase
from odoo.tools import mute_logger

from .common import SANDBOX_GET_ORDERS_PAYLOAD


class TestAmazBackendGetApi(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.backend = cls.env["amz.backend"].create(
            {
                "name": "Test Backend",
                "client_id": "test_client_id",
                "client_secret": "test_secret",
                "refresh_token": "test_refresh_token",
                "marketplace_id": "ATVPDKIKX0DER",
                "sandbox": True,
                "warehouse_id": cls.env["stock.warehouse"].search([], limit=1).id,
            }
        )

    def test_get_api_sandbox_endpoint(self):
        mock_api_class = MagicMock()
        self.backend._get_api(mock_api_class)
        call_kwargs = mock_api_class.call_args
        marketplace = call_kwargs.kwargs["marketplace"]
        self.assertIn(
            "sandbox.sellingpartnerapi-na",
            marketplace.endpoint,
            "Sandbox backend must use sandbox endpoint",
        )

    def test_get_api_production_endpoint(self):
        self.backend.sandbox = False
        mock_api_class = MagicMock()
        self.backend._get_api(mock_api_class)
        marketplace = mock_api_class.call_args.kwargs["marketplace"]
        self.assertNotIn(
            "sandbox",
            marketplace.endpoint,
            "Production backend must not use sandbox endpoint",
        )
        self.backend.sandbox = True

    def test_get_api_eu_marketplace(self):
        self.backend.marketplace_id = "A1PA6795UKMFR9"  # Germany
        mock_api_class = MagicMock()
        self.backend._get_api(mock_api_class)
        marketplace = mock_api_class.call_args.kwargs["marketplace"]
        self.assertIn("sellingpartnerapi-eu", marketplace.endpoint)
        self.backend.marketplace_id = "ATVPDKIKX0DER"

    def test_get_credentials_keys(self):
        creds = self.backend._get_credentials()
        self.assertIn("lwa_app_id", creds)
        self.assertIn("lwa_client_secret", creds)
        self.assertIn("refresh_token", creds)
        self.assertEqual(creds["lwa_app_id"], "test_client_id")

    @patch("sp_api.api.orders.orders_v0.OrdersV0.__init__", return_value=None)
    @patch("sp_api.api.orders.orders_v0.OrdersV0.get_orders")
    def test_action_test_connection_sandbox(self, mock_get_orders, _mock_init):
        mock_response = MagicMock()
        mock_response.payload = SANDBOX_GET_ORDERS_PAYLOAD
        mock_get_orders.return_value = mock_response

        result = self.backend.action_test_connection()
        self.assertEqual(result["tag"], "display_notification")
        self.assertEqual(result["params"]["type"], "success")
        mock_get_orders.assert_called_once()
        call_kwargs = mock_get_orders.call_args.kwargs
        self.assertEqual(call_kwargs["CreatedAfter"], "TEST_CASE_200")

    @patch("sp_api.api.orders.orders_v0.OrdersV0.__init__", return_value=None)
    @patch("sp_api.api.orders.orders_v0.OrdersV0.get_orders")
    def test_action_test_connection_production_branch(
        self, mock_get_orders, _mock_init
    ):
        """Non-sandbox uses a real CreatedAfter timestamp, not TEST_CASE_200."""
        self.backend.sandbox = False
        mock_response = MagicMock()
        mock_response.payload = SANDBOX_GET_ORDERS_PAYLOAD
        mock_get_orders.return_value = mock_response

        result = self.backend.action_test_connection()
        self.assertEqual(result["params"]["type"], "success")
        created_after = mock_get_orders.call_args.kwargs["CreatedAfter"]
        self.assertNotEqual(created_after, "TEST_CASE_200")
        self.assertTrue(created_after.endswith("Z"))

    @patch("sp_api.api.orders.orders_v0.OrdersV0.__init__", return_value=None)
    @patch("sp_api.api.orders.orders_v0.OrdersV0.get_orders")
    def test_action_test_connection_sp_api_error(self, mock_get_orders, _mock_init):
        from sp_api.base import SellingApiException

        mock_get_orders.side_effect = SellingApiException(
            [{"code": "InvalidInput", "message": "bad creds"}], {}
        )
        with self.assertRaises(UserError):
            self.backend.action_test_connection()

    @patch("sp_api.api.orders.orders_v0.OrdersV0.__init__", return_value=None)
    @patch("sp_api.api.orders.orders_v0.OrdersV0.get_orders")
    def test_action_test_connection_generic_error(self, mock_get_orders, _mock_init):
        mock_get_orders.side_effect = ValueError("boom")
        with self.assertRaises(UserError):
            self.backend.action_test_connection()

    @mute_logger("odoo.addons.connector_amazon.models.amz_backend")
    def test_import_orders_stub_is_noop(self):
        """Core's import_orders stub must not raise (overridden by _sale)."""
        self.backend.import_orders()

    def test_action_view_sale_order(self):
        partner = self.env["res.partner"].create({"name": "Amz Buyer"})
        sale = self.env["sale.order"].create({"partner_id": partner.id})
        order = self.env["amz.order"].create(
            {
                "backend_id": self.backend.id,
                "amz_order_id": "TEST-1",
                "sale_order_id": sale.id,
            }
        )
        action = order.action_view_sale_order()
        self.assertEqual(action["res_model"], "sale.order")
        self.assertEqual(action["res_id"], sale.id)
