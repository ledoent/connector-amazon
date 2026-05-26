from unittest.mock import MagicMock, patch

from odoo.tests.common import TransactionCase

AMZ_ORDER_ID = "902-1845936-5435065"


class TestConfirmShipment(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        warehouse = cls.env["stock.warehouse"].search([], limit=1)
        cls.backend = cls.env["amz.backend"].create({
            "name": "Stock Backend",
            "client_id": "cid",
            "client_secret": "csec",
            "refresh_token": "rtoken",
            "marketplace_id": "ATVPDKIKX0DER",
            "sandbox": True,
            "warehouse_id": warehouse.id,
        })
        partner = cls.env["res.partner"].create({"name": "Test Partner"})
        cls.sale = cls.env["sale.order"].create({
            "partner_id": partner.id,
            "warehouse_id": warehouse.id,
        })
        cls.amz_order = cls.env["amz.order"].create({
            "backend_id": cls.backend.id,
            "amz_order_id": AMZ_ORDER_ID,
            "sale_order_id": cls.sale.id,
        })
        cls.env["amz.order.line"].create({
            "amz_order_id": cls.amz_order.id,
            "order_item_id": "05015851154158",
            "asin": "B00551Q3CS",
            "seller_sku": "SKU001",
            "quantity_ordered": 1,
        })

    def _make_picking(self, tracking_ref=None, carrier_name="UPS"):
        carrier = self.env["delivery.carrier"].search([], limit=1)
        if not carrier:
            product = self.env["product.product"].create({"name": "Shipping"})
            carrier = self.env["delivery.carrier"].create({
                "name": carrier_name,
                "product_id": product.id,
            })
        picking = self.env["stock.picking"].create({
            "picking_type_id": self.env.ref("stock.picking_type_out").id,
            "location_id": self.env.ref("stock.stock_location_stock").id,
            "location_dest_id": self.env.ref("stock.stock_location_customers").id,
            "sale_id": self.sale.id,
            "carrier_id": carrier.id,
            "carrier_tracking_ref": tracking_ref,
        })
        return picking

    @patch("sp_api.api.Orders")
    def test_confirm_shipment_calls_api(self, mock_orders_class):
        api_instance = MagicMock()
        mock_orders_class.return_value = api_instance

        import datetime
        picking = self._make_picking(tracking_ref="1Z999AA10123456784")
        picking.date_done = datetime.datetime(2026, 5, 25, 10, 0, 0)

        self.backend._confirm_shipment(AMZ_ORDER_ID, picking.id)

        api_instance.confirm_shipment.assert_called_once()
        call_kwargs = api_instance.confirm_shipment.call_args.kwargs
        self.assertEqual(call_kwargs["order_id"], AMZ_ORDER_ID)
        pkg = call_kwargs["payload"]["packageDetail"]
        self.assertEqual(pkg["trackingNumber"], "1Z999AA10123456784")
        self.assertEqual(pkg["carrierCode"], "UPS")
        self.assertEqual(pkg["orderItems"][0]["orderItemId"], "05015851154158")

    @patch("sp_api.api.Orders")
    def test_confirm_shipment_skips_missing_tracking(self, mock_orders_class):
        api_instance = MagicMock()
        mock_orders_class.return_value = api_instance
        picking = self._make_picking(tracking_ref=None)

        self.backend._confirm_shipment(AMZ_ORDER_ID, picking.id)
        api_instance.confirm_shipment.assert_not_called()

    @patch("sp_api.api.Orders")
    def test_confirm_shipment_unknown_carrier_maps_to_other(self, mock_orders_class):
        api_instance = MagicMock()
        mock_orders_class.return_value = api_instance

        import datetime
        product = self.env["product.product"].create({"name": "Custom Ship"})
        carrier = self.env["delivery.carrier"].create({
            "name": "MyLocalCourier",
            "product_id": product.id,
        })
        picking = self.env["stock.picking"].create({
            "picking_type_id": self.env.ref("stock.picking_type_out").id,
            "location_id": self.env.ref("stock.stock_location_stock").id,
            "location_dest_id": self.env.ref("stock.stock_location_customers").id,
            "sale_id": self.sale.id,
            "carrier_id": carrier.id,
            "carrier_tracking_ref": "LOCAL123",
        })
        picking.date_done = datetime.datetime(2026, 5, 25, 10, 0, 0)

        self.backend._confirm_shipment(AMZ_ORDER_ID, picking.id)
        pkg = api_instance.confirm_shipment.call_args.kwargs["payload"]["packageDetail"]
        self.assertEqual(pkg["carrierCode"], "Other")
