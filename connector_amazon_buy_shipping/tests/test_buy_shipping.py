import base64
from unittest.mock import MagicMock, patch

from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase

RATES_PAYLOAD = {
    "ShippingServiceList": [
        {
            "ShippingServiceId": "UPS_GROUND",
            "ShippingServiceOfferId": "OFFER-UPS",
            "CarrierName": "UPS",
            "ShippingServiceName": "UPS Ground",
            "Rate": {"Amount": 8.50, "CurrencyCode": "USD"},
            "EarliestEstimatedDeliveryDate": "2026-06-02T00:00:00Z",
        },
        {
            "ShippingServiceId": "USPS_PM",
            "ShippingServiceOfferId": "OFFER-USPS",
            "CarrierName": "USPS",
            "ShippingServiceName": "Priority Mail",
            "Rate": {"Amount": 6.95, "CurrencyCode": "USD"},
            "EarliestEstimatedDeliveryDate": "2026-06-03T00:00:00Z",
        },
    ]
}

LABEL_B64 = base64.b64encode(b"%PDF-1.4 demo label").decode()

CREATE_PAYLOAD = {
    "ShipmentId": "SHIP-001",
    "TrackingId": "1Z999AA10123456784",
    "ShippingService": {
        "CarrierName": "USPS",
        "ShippingServiceName": "Priority Mail",
        "Rate": {"Amount": 6.95, "CurrencyCode": "USD"},
    },
    "Label": {"FileContents": {"Contents": LABEL_B64, "FileType": "PDF"}},
}


class TestBuyShipping(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.warehouse = cls.env["stock.warehouse"].search([], limit=1)
        cls.backend = cls.env["amz.backend"].create(
            {
                "name": "Buy Shipping Backend",
                "client_id": "cid",
                "client_secret": "csec",
                "refresh_token": "rtok",
                "marketplace_id": "ATVPDKIKX0DER",
                "sandbox": True,
                "warehouse_id": cls.warehouse.id,
            }
        )
        cls.partner = cls.env["res.partner"].create(
            {"name": "Buyer", "street": "1 Main", "city": "Reno", "zip": "89501"}
        )
        cls.product = cls.env["product.product"].create(
            {
                "name": "Ship Widget",
                "type": "consu",
                "is_storable": True,
                "weight": 1.0,
            }
        )
        cls.sale = cls.env["sale.order"].create(
            {
                "partner_id": cls.partner.id,
                "order_line": [
                    (0, 0, {"product_id": cls.product.id, "product_uom_qty": 2})
                ],
            }
        )
        cls.sale.action_confirm()
        cls.picking = cls.sale.picking_ids[:1]
        cls.amz_order = cls.env["amz.order"].create(
            {
                "backend_id": cls.backend.id,
                "amz_order_id": "112-AAA-0001",
                "fulfillment_channel": "MFN",
                "amazon_status": "Unshipped",
                "sale_order_id": cls.sale.id,
            }
        )
        cls.env["amz.order.line"].create(
            {
                "amz_order_id": cls.amz_order.id,
                "backend_id": cls.backend.id,
                "order_item_id": "ITEM-1",
                "seller_sku": "SHIP-SKU",
                "quantity_ordered": 2,
            }
        )

    def _wizard(self):
        return (
            self.env["amz.buy.shipping.wizard"]
            .with_context(default_picking_id=self.picking.id)
            .create({})
        )

    def test_get_rates_populates_options(self):
        wiz = self._wizard()
        # Weight pre-filled from product (1.0) * qty (2) = 2.0.
        self.assertEqual(wiz.weight, 2.0)
        with patch("sp_api.api.MerchantFulfillment") as mock_mf:
            api = MagicMock()
            mock_mf.return_value = api
            api.get_eligible_shipment_services.return_value = MagicMock(
                payload=RATES_PAYLOAD
            )
            wiz.action_get_rates()
        self.assertEqual(len(wiz.rate_line_ids), 2)
        usps = wiz.rate_line_ids.filtered(lambda r: r.carrier_name == "USPS")
        ups = wiz.rate_line_ids.filtered(lambda r: r.carrier_name == "UPS")
        self.assertEqual(usps.cost, 6.95)
        self.assertEqual(ups.cost, 8.50)
        self.assertEqual(usps.service_name, "Priority Mail")

    def _buy(self):
        wiz = self._wizard()
        with patch("sp_api.api.MerchantFulfillment") as mock_mf:
            api = MagicMock()
            mock_mf.return_value = api
            api.get_eligible_shipment_services.return_value = MagicMock(
                payload=RATES_PAYLOAD
            )
            api.create_shipment.return_value = MagicMock(payload=CREATE_PAYLOAD)
            wiz.action_get_rates()
            usps = wiz.rate_line_ids.filtered(lambda r: r.carrier_name == "USPS")
            usps.action_buy()
        return wiz

    def test_buy_label_sets_tracking_and_shipment(self):
        self._buy()
        self.picking.invalidate_recordset()
        self.assertEqual(self.picking.carrier_tracking_ref, "1Z999AA10123456784")
        self.assertTrue(self.picking.amazon_label_purchased)
        shipment = self.env["amz.shipment"].search(
            [("picking_id", "=", self.picking.id)]
        )
        self.assertEqual(len(shipment), 1)
        self.assertEqual(shipment.tracking_number, "1Z999AA10123456784")
        self.assertEqual(shipment.carrier_name, "USPS")
        self.assertEqual(shipment.cost, 6.95)
        self.assertTrue(shipment.label_attachment_id)
        self.assertEqual(shipment.order_id, self.amz_order)

    def test_download_label_returns_url(self):
        self._buy()
        shipment = self.env["amz.shipment"].search(
            [("picking_id", "=", self.picking.id)]
        )
        action = shipment.action_download_label()
        self.assertEqual(action["type"], "ir.actions.act_url")
        self.assertEqual(
            action["url"],
            f"/web/content/{shipment.label_attachment_id.id}?download=true",
        )

    def test_download_label_without_attachment(self):
        shipment = self.env["amz.shipment"].create({"picking_id": self.picking.id})
        self.assertFalse(shipment.action_download_label())

    def test_purchased_picking_skips_double_confirm(self):
        self._buy()
        # The label is already confirmed to Amazon; the tracking-push path must
        # skip this picking so ConfirmShipment is not also fired.
        jobs_before = self.env["queue.job"].search_count(
            [("method_name", "=", "_confirm_shipment")]
        )
        self.picking._enqueue_amazon_tracking_push()
        jobs_after = self.env["queue.job"].search_count(
            [("method_name", "=", "_confirm_shipment")]
        )
        self.assertEqual(jobs_before, jobs_after)

    def test_is_amazon_order_flag(self):
        self.assertTrue(self.picking.is_amazon_order)
        other = self.env["stock.picking"].create(
            {
                "picking_type_id": self.warehouse.out_type_id.id,
                "location_id": self.warehouse.lot_stock_id.id,
                "location_dest_id": self.env.ref("stock.stock_location_customers").id,
                "partner_id": self.partner.id,
            }
        )
        self.assertFalse(other.is_amazon_order)

    def test_shipment_request_body(self):
        details, order = self.backend._amz_shipment_request(
            self.picking, 2.0, 10.0, 8.0, 4.0
        )
        self.assertEqual(order, self.amz_order)
        self.assertEqual(details["AmazonOrderId"], "112-AAA-0001")
        self.assertEqual(
            details["ItemList"], [{"OrderItemId": "ITEM-1", "Quantity": 2}]
        )
        self.assertEqual(details["Weight"], {"Value": 2.0, "Unit": "oz"})
        self.assertIn("ShipFromAddress", details)

    def test_rate_fetch_surfaces_api_error(self):
        from sp_api.base import SellingApiException

        wiz = self._wizard()
        with patch("sp_api.api.MerchantFulfillment") as mock_mf:
            api = MagicMock()
            mock_mf.return_value = api
            api.get_eligible_shipment_services.side_effect = SellingApiException(
                [{"code": "InvalidInput", "message": "ineligible"}], {}
            )
            with self.assertRaises(UserError):
                wiz.action_get_rates()

    def test_double_purchase_blocked(self):
        wiz = self._buy()  # picking now flagged amazon_label_purchased
        rate = wiz.rate_line_ids[:1]
        with self.assertRaises(UserError):
            wiz._purchase(rate)

    def test_api_calls_use_positional_request_details(self):
        # Regression guard: the library takes shipment_request_details (and
        # shipping_service_id) positionally — passing them as kwargs raises a
        # TypeError at runtime that a permissive mock would not surface.
        wiz = self._wizard()
        with patch("sp_api.api.MerchantFulfillment") as mock_mf:
            api = MagicMock()
            mock_mf.return_value = api
            api.get_eligible_shipment_services.return_value = MagicMock(
                payload=RATES_PAYLOAD
            )
            api.create_shipment.return_value = MagicMock(payload=CREATE_PAYLOAD)
            wiz.action_get_rates()
            rate_args, _rate_kw = api.get_eligible_shipment_services.call_args
            self.assertEqual(rate_args[0]["AmazonOrderId"], "112-AAA-0001")
            wiz.rate_line_ids.filtered(lambda r: r.carrier_name == "USPS").action_buy()
            ship_args, ship_kw = api.create_shipment.call_args
            self.assertEqual(ship_args[0]["AmazonOrderId"], "112-AAA-0001")
            self.assertEqual(ship_args[1], "USPS_PM")
            self.assertEqual(ship_kw["ShippingServiceOfferId"], "OFFER-USPS")
