import json
from unittest.mock import MagicMock, patch

from odoo.tests.common import TransactionCase
from odoo.tools import mute_logger

AMZ_SKU = "REPRICE_TEST_SKU"
AMZ_ASIN = "B00REPRICE1"
SELLER_ID = "TEST_SELLER_ID"

LOGGER = "odoo.addons.connector_amazon_repricing.models.amz_backend"


def _make_notification(asin, buy_box_amount, seller_id=None, is_winner=False):
    """Build a minimal ANY_OFFER_CHANGED SQS payload (payloadVersion 1.0)."""
    offers = []
    if seller_id:
        offers.append(
            {
                "SellerId": seller_id,
                "IsBuyBoxWinner": is_winner,
                "ListingPrice": {
                    "Amount": str(buy_box_amount),
                    "CurrencyCode": "USD",
                },
            }
        )
    return {
        "payload": {
            "AnyOfferChangedNotification": {
                "OfferChangeTrigger": {
                    "ASIN": asin,
                    "MarketplaceId": "ATVPDKIKX0DER",
                },
                "Summary": {
                    "BuyBoxPrices": [
                        {
                            "Condition": "New",
                            "ListingPrice": {
                                "Amount": str(buy_box_amount),
                                "CurrencyCode": "USD",
                            },
                        }
                    ],
                    "BuyBoxEligibleOffers": [{"OfferCount": 1, "Condition": "New"}],
                },
                "Offers": offers,
            }
        }
    }


class TestRepricing(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.warehouse = cls.env["stock.warehouse"].search([], limit=1)
        cls.backend = cls.env["amz.backend"].create(
            {
                "name": "Test Repricing Backend",
                "client_id": "test_client_id",
                "client_secret": "test_secret",
                "refresh_token": "test_token",
                "marketplace_id": "ATVPDKIKX0DER",
                "sandbox": True,
                "warehouse_id": cls.warehouse.id,
                "seller_id": SELLER_ID,
                "pricing_mode": "competitive",
                "competitive_rule": "match_buy_box",
                "competitive_undercut_pct": 2.0,
                "competitive_floor_margin_pct": 15.0,
                "price_push_enabled": False,
                "notifications_enabled": True,
                "aws_access_key_id": "AKIATEST",
                "aws_secret_access_key": "testsecret",
                "aws_region": "us-east-1",
                "sqs_queue_url": "https://sqs.us-east-1.amazonaws.com/123/test-queue",
            }
        )
        cls.product = cls.env["product.product"].create(
            {
                "name": "Reprice Test Product",
                "default_code": AMZ_SKU,
                "type": "consu",
                "standard_price": 10.0,
            }
        )
        cls.listing = cls.env["amz.listing"].create(
            {
                "backend_id": cls.backend.id,
                "product_id": cls.product.id,
                "seller_sku": AMZ_SKU,
                "asin": AMZ_ASIN,
            }
        )

    # ── _process_offer_notification ───────────────────────────────────────────

    def test_process_notification_updates_buy_box_fields(self):
        payload = _make_notification(AMZ_ASIN, 25.00, seller_id="OTHER_SELLER")
        self.backend._process_offer_notification(payload)
        self.listing.invalidate_recordset()
        self.assertAlmostEqual(self.listing.buy_box_price, 25.00)
        self.assertEqual(self.listing.buy_box_winner, "competitor")

    def test_process_notification_buy_box_winner_us(self):
        payload = _make_notification(
            AMZ_ASIN, 30.00, seller_id=SELLER_ID, is_winner=True
        )
        self.backend._process_offer_notification(payload)
        self.listing.invalidate_recordset()
        self.assertEqual(self.listing.buy_box_winner, "us")

    # ── competitor offer history ──────────────────────────────────────────────

    def test_notification_persists_own_offer_snapshot(self):
        payload = _make_notification(
            AMZ_ASIN, 25.00, seller_id=SELLER_ID, is_winner=True
        )
        self.backend._process_offer_notification(payload)
        snaps = self.env["amz.offer.snapshot"].search(
            [("listing_id", "=", self.listing.id)]
        )
        self.assertEqual(len(snaps), 1)
        self.assertEqual(snaps.seller_id, SELLER_ID)
        self.assertTrue(snaps.is_own_offer)
        self.assertTrue(snaps.is_buy_box_winner)
        self.assertAlmostEqual(snaps.price, 25.00, places=2)
        self.assertEqual(snaps.asin, AMZ_ASIN)

    def test_notification_snapshot_marks_competitor(self):
        payload = _make_notification(
            AMZ_ASIN, 30.00, seller_id="OTHER_SELLER", is_winner=True
        )
        self.backend._process_offer_notification(payload)
        snap = self.env["amz.offer.snapshot"].search(
            [("listing_id", "=", self.listing.id)]
        )
        self.assertEqual(len(snap), 1)
        self.assertFalse(snap.is_own_offer)
        self.assertTrue(snap.is_buy_box_winner)

    def test_process_notification_no_buy_box_skips(self):
        self.listing.buy_box_price = 0.0
        payload = {
            "payload": {
                "AnyOfferChangedNotification": {
                    "OfferChangeTrigger": {"ASIN": AMZ_ASIN},
                    "Summary": {},
                    "Offers": [],
                }
            }
        }
        self.backend._process_offer_notification(payload)
        self.listing.invalidate_recordset()
        self.assertAlmostEqual(self.listing.buy_box_price, 0.0)

    def test_process_notification_unknown_asin_skips(self):
        payload = _make_notification("B00UNKNOWN1", 20.00)
        with mute_logger(LOGGER):
            self.backend._process_offer_notification(payload)

    def test_process_notification_triggers_reprice_if_enabled(self):
        self.backend.price_push_enabled = True
        payload = _make_notification(AMZ_ASIN, 25.00, seller_id="OTHER_SELLER")
        with patch.object(type(self.backend), "_reprice_listing") as mock_reprice:
            self.backend._process_offer_notification(payload)
        mock_reprice.assert_called_once_with(self.listing)
        self.backend.price_push_enabled = False

    # ── _compute_listing_price ────────────────────────────────────────────────

    def test_compute_price_match_buy_box(self):
        self.backend.competitive_rule = "match_buy_box"
        self.listing.buy_box_price = 50.0
        price = self.backend._compute_listing_price(self.listing)
        self.assertAlmostEqual(price, 50.0)

    def test_compute_price_undercut(self):
        self.backend.competitive_rule = "undercut_buy_box"
        self.backend.competitive_undercut_pct = 2.0
        self.listing.buy_box_price = 100.0
        price = self.backend._compute_listing_price(self.listing)
        self.assertAlmostEqual(price, 98.0)

    def test_compute_price_floor_applied(self):
        self.backend.competitive_rule = "undercut_buy_box"
        self.backend.competitive_undercut_pct = 50.0
        self.backend.competitive_floor_margin_pct = 15.0
        self.listing.buy_box_price = 10.0
        self.product.standard_price = 10.0
        price = self.backend._compute_listing_price(self.listing)
        # undercut gives 5.0; floor = 10 * 1.15 = 11.5
        self.assertAlmostEqual(price, 11.5)

    def test_compute_price_match_buy_box_respects_floor(self):
        self.backend.competitive_rule = "match_buy_box"
        self.backend.competitive_floor_margin_pct = 20.0
        self.listing.buy_box_price = 9.0
        self.product.standard_price = 10.0
        price = self.backend._compute_listing_price(self.listing)
        # buy box = 9.0, floor = 10 * 1.20 = 12.0 → price at floor
        self.assertAlmostEqual(price, 12.0)

    # ── _drain_sqs_queue ──────────────────────────────────────────────────────

    def test_drain_sqs_processes_and_deletes_messages(self):
        msg_body = _make_notification(AMZ_ASIN, 42.0)
        mock_sqs = MagicMock()
        mock_sqs.receive_message.side_effect = [
            {
                "Messages": [
                    {
                        "MessageId": "msg-1",
                        "ReceiptHandle": "rh-1",
                        "Body": json.dumps(msg_body),
                    }
                ]
            },
            {"Messages": []},
        ]

        with patch.object(type(self.backend), "_get_sqs_client", return_value=mock_sqs):
            self.backend._drain_sqs_queue()

        mock_sqs.delete_message.assert_called_once_with(
            QueueUrl=self.backend.sqs_queue_url,
            ReceiptHandle="rh-1",
        )
        self.listing.invalidate_recordset()
        self.assertAlmostEqual(self.listing.buy_box_price, 42.0)

    def test_drain_sqs_does_not_delete_on_parse_error(self):
        """Malformed messages must stay in queue (nack), not be deleted."""
        mock_sqs = MagicMock()
        mock_sqs.receive_message.side_effect = [
            {
                "Messages": [
                    {
                        "MessageId": "bad-msg",
                        "ReceiptHandle": "rh-bad",
                        "Body": "not-valid-json",
                    }
                ]
            },
            {"Messages": []},
        ]

        with (
            patch.object(type(self.backend), "_get_sqs_client", return_value=mock_sqs),
            mute_logger(LOGGER),
        ):
            self.backend._drain_sqs_queue()

        mock_sqs.delete_message.assert_not_called()

    # ── poll_offer_notifications (cron) ───────────────────────────────────────

    def test_poll_skips_backend_without_sqs_url(self):
        self.backend.sqs_queue_url = False
        called = []

        with patch.object(
            type(self.backend),
            "with_delay",
            side_effect=lambda **kw: called.append(kw) or MagicMock(),
        ):
            self.backend.poll_offer_notifications()

        self.assertEqual(called, [])
