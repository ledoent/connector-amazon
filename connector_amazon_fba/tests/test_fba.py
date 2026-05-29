from unittest.mock import MagicMock, patch

from odoo.tests.common import TransactionCase
from odoo.tools import mute_logger

try:
    from sp_api.base import SellingApiException
except ImportError:
    SellingApiException = Exception

SKU = "FBA-SKU-1"
ASIN = "B00FBA0001"
LOGGER = "odoo.addons.connector_amazon_fba.models.amz_backend"


def _summary(sku, asin, fulfillable, inbound=0, reserved=0, unsellable=0, total=None):
    return {
        "sellerSku": sku,
        "asin": asin,
        "fnSku": "X00" + sku,
        "totalQuantity": total if total is not None else fulfillable,
        "inventoryDetails": {
            "fulfillableQuantity": fulfillable,
            "inboundWorkingQuantity": inbound,
            "inboundShippedQuantity": 0,
            "inboundReceivingQuantity": 0,
            "reservedQuantity": {"totalReservedQuantity": reserved},
            "unfulfillableQuantity": {"totalUnfulfillableQuantity": unsellable},
        },
    }


def _mock_api(summaries, next_token=None):
    api = MagicMock()
    resp = MagicMock()
    resp.payload = {"inventorySummaries": summaries}
    resp.next_token = next_token
    api.get_inventory_summary_marketplace.return_value = resp
    return api


class TestFbaInventory(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.backend = cls.env["amz.backend"].create(
            {
                "name": "FBA Backend",
                "client_id": "cid",
                "client_secret": "csec",
                "refresh_token": "rtok",
                "marketplace_id": "ATVPDKIKX0DER",
                "sandbox": True,
                "warehouse_id": cls.env["stock.warehouse"].search([], limit=1).id,
            }
        )
        cls.product = cls.env["product.product"].create(
            {
                "name": "FBA Product",
                "default_code": SKU,
                "type": "consu",
                "is_storable": True,
            }
        )

    def _set_on_hand(self, product, qty):
        self.env["stock.quant"]._update_available_quantity(
            product,
            self.backend.warehouse_id.lot_stock_id,
            qty,
        )

    # ── upsert + drift ────────────────────────────────────────────────────────

    def test_pull_creates_record_with_drift(self):
        self._set_on_hand(self.product, 3)  # Odoo on-hand 3
        api = _mock_api([_summary(SKU, ASIN, fulfillable=10, inbound=5, reserved=1)])
        with patch.object(type(self.backend), "_get_api", return_value=api):
            self.backend._pull_fba_inventory()

        rec = self.env["amz.fba.inventory"].search(
            [("backend_id", "=", self.backend.id), ("seller_sku", "=", SKU)]
        )
        self.assertEqual(len(rec), 1)
        self.assertEqual(rec.product_id, self.product)
        self.assertAlmostEqual(rec.fulfillable_qty, 10.0)
        self.assertAlmostEqual(rec.inbound_qty, 5.0)
        self.assertAlmostEqual(rec.reserved_qty, 1.0)
        self.assertAlmostEqual(rec.odoo_qty, 3.0)
        self.assertAlmostEqual(rec.drift, 7.0)  # 10 fulfillable − 3 on-hand
        self.backend.invalidate_recordset()
        self.assertTrue(self.backend.last_fba_sync_date)

    def test_pull_is_idempotent(self):
        api = _mock_api([_summary(SKU, ASIN, fulfillable=10)])
        with patch.object(type(self.backend), "_get_api", return_value=api):
            self.backend._pull_fba_inventory()
            self.backend._pull_fba_inventory()
        recs = self.env["amz.fba.inventory"].search(
            [("backend_id", "=", self.backend.id), ("seller_sku", "=", SKU)]
        )
        self.assertEqual(len(recs), 1, "re-sync must update, not duplicate")

    def test_pull_follows_pagination(self):
        page1 = MagicMock()
        page1.payload = {"inventorySummaries": [_summary(SKU, ASIN, fulfillable=4)]}
        page1.next_token = "tok2"
        page2 = MagicMock()
        page2.payload = {
            "inventorySummaries": [_summary("FBA-SKU-2", "B00FBA0002", fulfillable=2)]
        }
        page2.next_token = None
        api = MagicMock()
        api.get_inventory_summary_marketplace.side_effect = [page1, page2]
        with patch.object(type(self.backend), "_get_api", return_value=api):
            self.backend._pull_fba_inventory()
        self.assertEqual(api.get_inventory_summary_marketplace.call_count, 2)
        recs = self.env["amz.fba.inventory"].search(
            [("backend_id", "=", self.backend.id)]
        )
        self.assertEqual(len(recs), 2)

    def test_pull_unknown_sku_has_no_product(self):
        api = _mock_api([_summary("NO_MATCH", "B00X", fulfillable=5)])
        with patch.object(type(self.backend), "_get_api", return_value=api):
            self.backend._pull_fba_inventory()
        rec = self.env["amz.fba.inventory"].search([("seller_sku", "=", "NO_MATCH")])
        self.assertTrue(rec)
        self.assertFalse(rec.product_id)
        self.assertAlmostEqual(rec.odoo_qty, 0.0)
        self.assertAlmostEqual(rec.drift, 5.0)

    # ── action / cron ─────────────────────────────────────────────────────────

    def test_action_enqueues_job(self):
        queued = []
        with patch.object(
            type(self.backend),
            "with_delay",
            side_effect=lambda **kw: queued.append(kw) or MagicMock(),
        ):
            result = self.backend.action_sync_fba_inventory()
        self.assertTrue(queued)
        self.assertEqual(result["tag"], "display_notification")

    def test_cron_skips_disabled_backend(self):
        self.backend.amazon_fba_enabled = False
        called = []
        with patch.object(
            type(self.backend),
            "with_delay",
            side_effect=lambda **kw: called.append(kw) or MagicMock(),
        ):
            self.backend.sync_fba_inventory()
        self.assertEqual(called, [], "disabled backend must be skipped")

    def test_pull_api_error_propagates(self):
        api = MagicMock()
        api.get_inventory_summary_marketplace.side_effect = SellingApiException(
            [{"code": "QuotaExceeded", "message": "Too many requests"}], headers={}
        )
        with (
            patch.object(type(self.backend), "_get_api", return_value=api),
            mute_logger(LOGGER),
            self.assertRaises(SellingApiException),
        ):
            self.backend._pull_fba_inventory()
        # Nothing persisted on a failed pull.
        self.assertFalse(
            self.env["amz.fba.inventory"].search([("backend_id", "=", self.backend.id)])
        )
