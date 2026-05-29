from datetime import timedelta
from unittest.mock import MagicMock, patch

from odoo import fields
from odoo.tests.common import TransactionCase


class TestShipRisk(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.warehouse = cls.env["stock.warehouse"].search([], limit=1)
        cls.backend = cls.env["amz.backend"].create(
            {
                "name": "Ship Risk Backend",
                "client_id": "cid",
                "client_secret": "csec",
                "refresh_token": "rtok",
                "marketplace_id": "ATVPDKIKX0DER",
                "sandbox": True,
                "warehouse_id": cls.warehouse.id,
                "ship_risk_threshold_hours": 24.0,
            }
        )
        cls.partner = cls.env["res.partner"].create({"name": "Ship Cust"})
        cls.product = cls.env["product.product"].create(
            {
                "name": "Ship Widget",
                "default_code": "SHIP-SKU",
                "type": "consu",
                "is_storable": True,
            }
        )

    _seq = 0

    def _order(self, status="Unshipped", channel="MFN", cutoff=None, sale=False):
        type(self)._seq += 1
        return self.env["amz.order"].create(
            {
                "backend_id": self.backend.id,
                "amz_order_id": f"ORD-{type(self)._seq:04d}",
                "amazon_status": status,
                "fulfillment_channel": channel,
                "latest_ship_date": cutoff,
                "sale_order_id": sale.id if sale else False,
            }
        )

    def test_overdue(self):
        past = fields.Datetime.now() - timedelta(hours=1)
        order = self._order(cutoff=past)
        order._update_ship_risk()
        self.assertEqual(order.ship_risk, "overdue")

    def test_at_risk_within_threshold(self):
        soon = fields.Datetime.now() + timedelta(hours=2)
        order = self._order(cutoff=soon)
        order._update_ship_risk()
        self.assertEqual(order.ship_risk, "at_risk")
        self.assertGreater(order.ship_deadline_hours, 0.0)

    def test_on_track_when_far_out(self):
        far = fields.Datetime.now() + timedelta(hours=100)
        order = self._order(cutoff=far)
        order._update_ship_risk()
        self.assertEqual(order.ship_risk, "on_track")

    def test_blocked_when_picking_unreserved(self):
        # Confirm a sale order with no stock -> delivery picking is not assigned.
        sale = self.env["sale.order"].create(
            {
                "partner_id": self.partner.id,
                "order_line": [
                    (0, 0, {"product_id": self.product.id, "product_uom_qty": 3})
                ],
            }
        )
        sale.action_confirm()
        self.assertTrue(sale.picking_ids)
        self.assertNotIn("assigned", sale.picking_ids.mapped("state"))
        far = fields.Datetime.now() + timedelta(hours=100)
        order = self._order(cutoff=far, sale=sale)
        order._update_ship_risk()
        # Plenty of time, but stock can't be reserved -> blocked.
        self.assertEqual(order.ship_risk, "blocked")

    def test_fba_orders_ignored(self):
        soon = fields.Datetime.now() + timedelta(hours=1)
        order = self._order(channel="AFN", cutoff=soon)
        order._update_ship_risk()
        self.assertEqual(order.ship_risk, "none")

    def test_shipped_orders_ignored(self):
        past = fields.Datetime.now() - timedelta(hours=1)
        order = self._order(status="Shipped", cutoff=past)
        order._update_ship_risk()
        self.assertEqual(order.ship_risk, "none")

    def test_parse_amz_datetime(self):
        parsed = self.backend._parse_amz_datetime("2026-06-01T23:59:59Z")
        self.assertEqual(str(parsed), "2026-06-01 23:59:59")
        self.assertFalse(self.backend._parse_amz_datetime(None))

    def test_capture_ship_dates_from_get_order(self):
        order = self._order(channel=False, cutoff=False)
        payload = {
            "LatestShipDate": "2099-01-02T23:59:59Z",
            "EarliestShipDate": "2099-01-01T00:00:00Z",
            "FulfillmentChannel": "MFN",
            "OrderStatus": "Unshipped",
        }
        with patch("sp_api.api.Orders") as mock_orders:
            api = MagicMock()
            mock_orders.return_value = api
            api.get_order.return_value = MagicMock(payload=payload)
            self.backend._amz_capture_ship_dates(order.amz_order_id)
        order.invalidate_recordset()
        self.assertEqual(str(order.latest_ship_date), "2099-01-02 23:59:59")
        self.assertEqual(order.fulfillment_channel, "MFN")
        # Far-future cutoff, no picking -> on track after capture refreshes risk.
        self.assertEqual(order.ship_risk, "on_track")
