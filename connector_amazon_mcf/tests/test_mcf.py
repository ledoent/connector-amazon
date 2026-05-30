from unittest.mock import MagicMock, patch

from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase

GET_PAYLOAD = {
    "fulfillmentOrder": {"fulfillmentOrderStatus": "Complete"},
    "fulfillmentShipments": [
        {
            "fulfillmentShipmentStatus": "SHIPPED",
            "fulfillmentShipmentPackage": [
                {"packageNumber": 1, "carrierCode": "USPS", "trackingNumber": "TRK-9"}
            ],
        }
    ],
}


class TestMcf(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.warehouse = cls.env["stock.warehouse"].search([], limit=1)
        cls.backend = cls.env["amz.backend"].create(
            {
                "name": "MCF Backend",
                "client_id": "cid",
                "client_secret": "csec",
                "refresh_token": "rtok",
                "marketplace_id": "ATVPDKIKX0DER",
                "sandbox": True,
                "warehouse_id": cls.warehouse.id,
                "mcf_default_speed": "Standard",
            }
        )
        cls.partner = cls.env["res.partner"].create(
            {"name": "Channel Buyer", "street": "5 Oak", "city": "Reno", "zip": "89501"}
        )
        cls.product = cls.env["product.product"].create(
            {"name": "MCF Widget", "type": "consu", "is_storable": True}
        )
        cls.fba = cls.env["amz.fba.inventory"].create(
            {
                "backend_id": cls.backend.id,
                "seller_sku": "MCF-SKU-1",
                "product_id": cls.product.id,
            }
        )
        cls.sale = cls.env["sale.order"].create(
            {
                "partner_id": cls.partner.id,
                "order_line": [
                    (0, 0, {"product_id": cls.product.id, "product_uom_qty": 3})
                ],
            }
        )
        cls.sale.action_confirm()
        cls.picking = cls.sale.picking_ids[:1]

    def _fo(self, picking=None):
        picking = picking or self.picking
        picking.action_amz_mcf_fulfill()
        return self.env["amz.fulfillment.order"].search(
            [("picking_id", "=", picking.id)], limit=1
        )

    def _outgoing_picking(self, qtys):
        """A bare outgoing delivery with one move per quantity in ``qtys``."""
        wh = self.warehouse
        customers = self.env.ref("stock.stock_location_customers")
        picking = self.env["stock.picking"].create(
            {
                "picking_type_id": wh.out_type_id.id,
                "location_id": wh.lot_stock_id.id,
                "location_dest_id": customers.id,
                "partner_id": self.partner.id,
            }
        )
        for qty in qtys:
            self.env["stock.move"].create(
                {
                    "product_id": self.product.id,
                    "product_uom_qty": qty,
                    "product_uom": self.product.uom_id.id,
                    "picking_id": picking.id,
                    "location_id": wh.lot_stock_id.id,
                    "location_dest_id": customers.id,
                }
            )
        return picking

    def test_fulfill_creates_draft_order(self):
        fo = self._fo()
        self.assertEqual(fo.state, "draft")
        self.assertEqual(fo.name, self.picking.name)
        self.assertEqual(len(fo.line_ids), 1)
        self.assertEqual(fo.line_ids.seller_sku, "MCF-SKU-1")
        self.assertEqual(fo.line_ids.quantity, 3)
        self.assertEqual(fo.partner_id, self.partner)

    def test_fulfill_requires_fba_sku(self):
        self.fba.unlink()
        with self.assertRaises(UserError):
            self.picking.action_amz_mcf_fulfill()

    def test_submit_sends_order(self):
        fo = self._fo()
        with patch("sp_api.api.FulfillmentOutbound") as mock_fo:
            api = MagicMock()
            mock_fo.return_value = api
            fo.action_submit()
            _args, kwargs = api.create_fulfillment_order.call_args
        self.assertEqual(fo.state, "submitted")
        self.assertEqual(kwargs["sellerFulfillmentOrderId"], self.picking.name)
        self.assertEqual(kwargs["items"][0]["sellerSku"], "MCF-SKU-1")
        self.assertEqual(kwargs["destinationAddress"]["postalCode"], "89501")

    def test_check_status_writes_tracking_back(self):
        fo = self._fo()
        fo.state = "submitted"
        with patch("sp_api.api.FulfillmentOutbound") as mock_fo:
            api = MagicMock()
            mock_fo.return_value = api
            api.get_fulfillment_order.return_value = MagicMock(payload=GET_PAYLOAD)
            fo.action_check_status()
            # Regression guard: id is passed positionally.
            args, _kw = api.get_fulfillment_order.call_args
            self.assertEqual(args[0], self.picking.name)
        self.assertEqual(fo.state, "complete")
        self.assertEqual(fo.amazon_status, "Complete")
        self.assertEqual(fo.tracking_numbers, "TRK-9")
        self.assertEqual(self.picking.carrier_tracking_ref, "TRK-9")

    def test_cancel_submitted_order(self):
        fo = self._fo()
        fo.state = "submitted"
        with patch("sp_api.api.FulfillmentOutbound") as mock_fo:
            api = MagicMock()
            mock_fo.return_value = api
            fo.action_cancel()
            args, _kw = api.cancel_fulfillment_order.call_args
            self.assertEqual(args[0], self.picking.name)
        self.assertEqual(fo.state, "cancelled")

    def test_cancel_draft_skips_amazon(self):
        """A never-submitted order is cancelled locally without an API call."""
        fo = self._fo()
        with patch("sp_api.api.FulfillmentOutbound") as mock_fo:
            api = MagicMock()
            mock_fo.return_value = api
            fo.action_cancel()
            api.cancel_fulfillment_order.assert_not_called()
        self.assertEqual(fo.state, "cancelled")

    def test_submit_requires_draft(self):
        fo = self._fo()
        fo.state = "submitted"
        with self.assertRaises(UserError):
            fo.action_submit()

    def test_submit_requires_lines(self):
        fo = self._fo()
        fo.line_ids.unlink()
        with self.assertRaises(UserError):
            fo.action_submit()

    def test_fulfill_aggregates_duplicate_sku(self):
        """Two move lines of the same product collapse into one MCF line with a
        unique item_id and the summed quantity."""
        picking = self._outgoing_picking([2, 5])
        fo = self._fo(picking)
        self.assertEqual(len(fo.line_ids), 1)
        self.assertEqual(fo.line_ids.quantity, 7)
        self.assertEqual(fo.line_ids.item_id, "MCF-SKU-1")

    def test_submit_wraps_sp_api_error(self):
        from sp_api.base import SellingApiException

        fo = self._fo()
        with patch("sp_api.api.FulfillmentOutbound") as mock_fo:
            api = MagicMock()
            mock_fo.return_value = api
            api.create_fulfillment_order.side_effect = SellingApiException(
                [{"code": "InvalidInput", "message": "boom"}], {}
            )
            with self.assertRaises(UserError):
                fo.action_submit()
        self.assertEqual(fo.state, "draft")
