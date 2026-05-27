from unittest.mock import MagicMock, patch

from odoo.tests.common import TransactionCase
from odoo.tools import mute_logger

AMZ_SKU = "REPRICE_TEST_SKU"
AMZ_ASIN = "B00REPRICE1"

LOGGER = "odoo.addons.connector_amazon_repricing.models.amz_backend"


def _make_notification(asin, buy_box_amount, is_winner=False):
    return {
        "payload": {
            "AnyOfferChangedNotification": {
                "OfferChangeSummary": {
                    "ASIN": asin,
                    "BuyBoxPrice": {"Amount": str(buy_box_amount)},
                    "BuyBoxEligibleOffers": {"IsBuyBoxWinner": is_winner},
                }
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
                "seller_id": "TEST_SELLER_ID",
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
        payload = _make_notification(AMZ_ASIN, 25.00, is_winner=False)
        self.backend._process_offer_notification(payload)
        self.assertAlmostEqual(self.listing.buy_box_price, 25.00)
        self.assertEqual(self.listing.buy_box_winner, "competitor")

    def test_process_notification_buy_box_winner_us(self):
        payload = _make_notification(AMZ_ASIN, 30.00, is_winner=True)
        self.backend._process_offer_notification(payload)
        self.assertEqual(self.listing.buy_box_winner, "us")

    def test_process_notification_no_buy_box_skips(self):
        payload = {
            "payload": {
                "AnyOfferChangedNotification": {
                    "OfferChangeSummary": {
                        "ASIN": AMZ_ASIN,
                    }
                }
            }
        }
        original_price = self.listing.buy_box_price
        self.backend._process_offer_notification(payload)
        self.assertEqual(self.listing.buy_box_price, original_price)

    def test_process_notification_unknown_asin_skips(self):
        payload = _make_notification("B00UNKNOWN1", 20.00)
        with mute_logger(LOGGER):
            self.backend._process_offer_notification(payload)

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
        # undercut would give 5.0, floor = 10 * 1.15 = 11.5
        self.assertAlmostEqual(price, 11.5)

    # ── _drain_sqs_queue ──────────────────────────────────────────────────────

    def test_drain_sqs_processes_and_deletes_messages(self):
        msg_body = _make_notification(AMZ_ASIN, 42.0)
        import json

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
        self.assertAlmostEqual(self.listing.buy_box_price, 42.0)

    def test_drain_sqs_deletes_even_on_parse_error(self):
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

        mock_sqs.delete_message.assert_called_once_with(
            QueueUrl=self.backend.sqs_queue_url,
            ReceiptHandle="rh-bad",
        )

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
        self.backend.sqs_queue_url = (
            "https://sqs.us-east-1.amazonaws.com/123/test-queue"
        )
