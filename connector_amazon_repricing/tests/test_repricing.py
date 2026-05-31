import json
from unittest.mock import MagicMock, patch

from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase
from odoo.tools import mute_logger

from odoo.addons.connector_amazon_repricing.models.amz_backend import _SQS_MAX_MESSAGES

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

    def test_drain_sqs_multi_batch_loop(self):
        """receive_message is called until it returns no messages (multi-page)."""
        page1 = {
            "Messages": [
                {
                    "MessageId": f"m{i}",
                    "ReceiptHandle": f"rh{i}",
                    "Body": json.dumps(_make_notification(AMZ_ASIN, 10.0 + i)),
                }
                for i in range(_SQS_MAX_MESSAGES)
            ]
        }
        page2 = {
            "Messages": [
                {
                    "MessageId": "m-last",
                    "ReceiptHandle": "rh-last",
                    "Body": json.dumps(_make_notification(AMZ_ASIN, 99.0)),
                }
            ]
        }
        mock_sqs = MagicMock()
        mock_sqs.receive_message.side_effect = [page1, page2, {"Messages": []}]

        with patch.object(type(self.backend), "_get_sqs_client", return_value=mock_sqs):
            self.backend._drain_sqs_queue()

        # Three receive calls (two full-ish pages + the terminating empty page),
        # one delete per processed message.
        self.assertEqual(mock_sqs.receive_message.call_count, 3)
        self.assertEqual(mock_sqs.delete_message.call_count, _SQS_MAX_MESSAGES + 1)

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

    def test_poll_enqueues_drain_for_enabled_backend(self):
        """An enabled backend with a queue URL enqueues a drain job."""
        called = []

        with patch.object(
            type(self.backend),
            "with_delay",
            side_effect=lambda **kw: called.append(kw) or MagicMock(),
        ):
            self.backend.poll_offer_notifications()

        self.assertEqual(len(called), 1)

    # ── action_setup_notifications ────────────────────────────────────────────

    def test_setup_notifications_requires_aws_credentials(self):
        self.backend.aws_access_key_id = False
        with self.assertRaises(UserError):
            self.backend.action_setup_notifications()

    def test_setup_notifications_requires_queue_url(self):
        self.backend.sqs_queue_url = False
        with self.assertRaises(UserError):
            self.backend.action_setup_notifications()

    def test_setup_notifications_happy_path(self):
        """ARN is derived from SQS then a destination + subscription are created."""
        mock_sqs = MagicMock()
        mock_sqs.get_queue_attributes.return_value = {
            "Attributes": {"QueueArn": "arn:aws:sqs:us-east-1:123:test-queue"}
        }
        mock_api = MagicMock()
        mock_api.create_destination.return_value = MagicMock(
            payload={"destinationId": "dest-123"}
        )

        with (
            patch.object(type(self.backend), "_get_sqs_client", return_value=mock_sqs),
            patch.object(type(self.backend), "_get_api", return_value=mock_api),
        ):
            self.backend.action_setup_notifications()

        dest_body = mock_api.create_destination.call_args.kwargs["body"]
        self.assertEqual(
            dest_body["resourceSpecification"]["sqs"]["arn"],
            "arn:aws:sqs:us-east-1:123:test-queue",
        )
        sub_kwargs = mock_api.create_subscription.call_args.kwargs
        self.assertEqual(sub_kwargs["notificationType"], "ANY_OFFER_CHANGED")
        self.assertEqual(sub_kwargs["body"]["destinationId"], "dest-123")

    # ── _snapshot_offers fallbacks ────────────────────────────────────────────

    def test_snapshot_offers_handles_missing_fields(self):
        """An offer missing SellerId/ListingPrice yields a snapshot with safe
        defaults (not own offer, price 0)."""
        self.backend._snapshot_offers(self.listing, [{"IsBuyBoxWinner": False}])
        snap = self.env["amz.offer.snapshot"].search(
            [("listing_id", "=", self.listing.id)]
        )
        self.assertEqual(len(snap), 1)
        self.assertFalse(snap.is_own_offer)
        self.assertAlmostEqual(snap.price, 0.0, places=2)

    def test_snapshot_offers_empty_list_creates_nothing(self):
        self.backend._snapshot_offers(self.listing, [])
        snap = self.env["amz.offer.snapshot"].search(
            [("listing_id", "=", self.listing.id)]
        )
        self.assertFalse(snap)

    # ── _reprice_listing / _push_single_listing ───────────────────────────────

    def test_reprice_listing_unchanged_price_does_not_push(self):
        """When the computed target equals the current price, no push is queued."""
        self.listing.buy_box_price = 50.0
        self.listing.current_list_price = 50.0
        self.backend.competitive_rule = "match_buy_box"
        self.backend.competitive_floor_margin_pct = 0.0
        queued = []
        with patch.object(
            type(self.backend),
            "with_delay",
            side_effect=lambda **kw: queued.append(kw) or MagicMock(),
        ):
            self.backend._reprice_listing(self.listing)
        self.assertEqual(queued, [])
        self.assertAlmostEqual(self.listing.computed_target_price, 50.0, places=2)

    def test_reprice_listing_changed_price_queues_push(self):
        self.listing.buy_box_price = 60.0
        self.listing.current_list_price = 50.0
        self.backend.competitive_rule = "match_buy_box"
        self.backend.competitive_floor_margin_pct = 0.0
        queued = []
        with patch.object(
            type(self.backend),
            "with_delay",
            side_effect=lambda **kw: queued.append(kw) or MagicMock(),
        ):
            self.backend._reprice_listing(self.listing)
        self.assertEqual(len(queued), 1)

    def test_push_single_listing_success_logs_notification(self):
        """A successful push writes the price and a 'notification' history row."""
        self.listing.current_list_price = 20.0
        mock_api = MagicMock()
        with patch.object(type(self.backend), "_get_api", return_value=mock_api):
            self.backend._push_single_listing(self.listing.id, 24.99)

        self.assertTrue(mock_api.patch_listings_item.called)
        self.listing.invalidate_recordset()
        self.assertAlmostEqual(self.listing.current_list_price, 24.99, places=2)
        self.assertTrue(self.listing.last_price_push_date)
        hist = self.env["amz.price.history"].search(
            [("listing_id", "=", self.listing.id)]
        )
        self.assertEqual(len(hist), 1)
        self.assertEqual(hist.trigger, "notification")
        self.assertAlmostEqual(hist.new_price, 24.99, places=2)

    def test_push_single_listing_skips_deleted_listing(self):
        """A listing removed before the job runs is a no-op (exists() guard)."""
        listing_id = self.listing.id
        self.listing.unlink()
        mock_api = MagicMock()
        with patch.object(type(self.backend), "_get_api", return_value=mock_api):
            self.backend._push_single_listing(listing_id, 30.0)
        mock_api.patch_listings_item.assert_not_called()

    def test_push_single_listing_swallows_api_error(self):
        """An API error is caught and logged, not raised, leaving price unchanged."""
        self.listing.current_list_price = 20.0
        mock_api = MagicMock()
        mock_api.patch_listings_item.side_effect = Exception("API down")
        with (
            patch.object(type(self.backend), "_get_api", return_value=mock_api),
            mute_logger(LOGGER),
        ):
            self.backend._push_single_listing(self.listing.id, 24.99)
        self.listing.invalidate_recordset()
        self.assertAlmostEqual(self.listing.current_list_price, 20.0, places=2)
