from unittest.mock import MagicMock, patch

from odoo.tests.common import TransactionCase

from odoo.addons.connector_amazon.tests.common import (
    SANDBOX_GET_ORDER_ADDRESS_PAYLOAD,
    SANDBOX_GET_ORDER_ITEMS_PAYLOAD,
    SANDBOX_GET_ORDERS_PAYLOAD,
)

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
        with patch.object(self.backend, "with_delay") as mock_delay:
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
        with patch.object(self.backend, "with_delay", return_value=MagicMock()):
            self.backend.import_orders()
        self.assertTrue(self.backend.last_import_date)

    @patch("sp_api.api.Orders")
    def test_import_order_creates_amz_order(self, mock_orders_class):
        self._mock_orders_api(mock_orders_class)
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
