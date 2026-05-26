from unittest.mock import MagicMock, patch

from odoo.tests.common import TransactionCase

AMZ_ORDER_ID = "902-1845936-5435065"


class TestTrackingPush(TransactionCase):
    """Test that stock.picking._action_done triggers the tracking push job."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        warehouse = cls.env["stock.warehouse"].search([], limit=1)
        cls.backend = cls.env["amz.backend"].create(
            {
                "name": "Tracking Backend",
                "client_id": "cid",
                "client_secret": "csec",
                "refresh_token": "rtoken",
                "marketplace_id": "ATVPDKIKX0DER",
                "sandbox": True,
                "warehouse_id": warehouse.id,
            }
        )
        partner = cls.env["res.partner"].create({"name": "Ship Partner"})
        cls.sale = cls.env["sale.order"].create(
            {
                "partner_id": partner.id,
                "warehouse_id": warehouse.id,
            }
        )
        cls.env["amz.order"].create(
            {
                "backend_id": cls.backend.id,
                "amz_order_id": AMZ_ORDER_ID,
                "sale_order_id": cls.sale.id,
            }
        )

    def test_enqueues_job_when_picking_has_tracking(self):
        product = self.env["product.product"].create({"name": "Ship Product"})
        carrier = self.env["delivery.carrier"].create(
            {
                "name": "UPS",
                "product_id": product.id,
            }
        )
        picking = self.env["stock.picking"].create(
            {
                "picking_type_id": self.env.ref("stock.picking_type_out").id,
                "location_id": self.env.ref("stock.stock_location_stock").id,
                "location_dest_id": self.env.ref("stock.stock_location_customers").id,
                "sale_id": self.sale.id,
                "carrier_id": carrier.id,
                "carrier_tracking_ref": "1ZTEST",
            }
        )

        with patch.object(self.backend, "with_delay") as mock_delay:
            delayed = MagicMock()
            mock_delay.return_value = delayed
            picking._enqueue_amazon_tracking_push()

        mock_delay.assert_called_once()
        delayed._confirm_shipment.assert_called_once_with(AMZ_ORDER_ID, picking.id)

    def test_skips_picking_without_sale(self):
        picking = self.env["stock.picking"].create(
            {
                "picking_type_id": self.env.ref("stock.picking_type_out").id,
                "location_id": self.env.ref("stock.stock_location_stock").id,
                "location_dest_id": self.env.ref("stock.stock_location_customers").id,
                "carrier_tracking_ref": "NOREF",
            }
        )
        with patch.object(self.backend, "with_delay") as mock_delay:
            picking._enqueue_amazon_tracking_push()
        mock_delay.assert_not_called()

    def test_skips_picking_without_tracking_ref(self):
        picking = self.env["stock.picking"].create(
            {
                "picking_type_id": self.env.ref("stock.picking_type_out").id,
                "location_id": self.env.ref("stock.stock_location_stock").id,
                "location_dest_id": self.env.ref("stock.stock_location_customers").id,
                "sale_id": self.sale.id,
            }
        )
        with patch.object(self.backend, "with_delay") as mock_delay:
            picking._enqueue_amazon_tracking_push()
        mock_delay.assert_not_called()
