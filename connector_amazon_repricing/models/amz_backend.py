import json
import logging

from odoo import fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

# SQS batch maximum
_SQS_MAX_MESSAGES = 10


class AmazonBackend(models.Model):
    _inherit = "amz.backend"

    aws_access_key_id = fields.Char("AWS Access Key ID")
    aws_secret_access_key = fields.Char("AWS Secret Access Key")
    aws_region = fields.Char("AWS Region", default="us-east-1")
    sqs_queue_url = fields.Char(
        "SQS Queue URL",
        help=(
            "URL of the pre-provisioned SQS queue. "
            "The queue must have the SP-API send policy attached."
        ),
    )
    notifications_enabled = fields.Boolean("Real-Time Repricing", default=False)

    # ── SQS client ────────────────────────────────────────────────────────────

    def _get_sqs_client(self):
        """Return an authenticated boto3 SQS client for this backend's region."""
        try:
            import boto3
        except ImportError as exc:
            raise UserError(
                self.env._(
                    "boto3 is required for SQS polling."
                    " Install it with: pip install boto3"
                )
            ) from exc
        return boto3.client(
            "sqs",
            region_name=self.aws_region,
            aws_access_key_id=self.aws_access_key_id,
            aws_secret_access_key=self.aws_secret_access_key,
        )

    # ── Notification subscription setup ──────────────────────────────────────

    def action_setup_notifications(self):
        """Register SQS destination with Amazon and subscribe ANY_OFFER_CHANGED."""
        self.ensure_one()
        if not self.aws_access_key_id or not self.aws_secret_access_key:
            raise UserError(
                self.env._("AWS credentials are required to set up notifications.")
            )
        if not self.sqs_queue_url:
            raise UserError(
                self.env._("SQS Queue URL is required to set up notifications.")
            )

        from sp_api.api import Notifications

        api = self._get_api(Notifications)

        # Derive the SQS queue ARN from the URL the user provisioned externally.
        # Amazon requires the ARN (not URL) when registering the destination.
        sqs = self._get_sqs_client()
        queue_attrs = sqs.get_queue_attributes(
            QueueUrl=self.sqs_queue_url,
            AttributeNames=["QueueArn"],
        )
        queue_arn = queue_attrs["Attributes"]["QueueArn"]

        dest = api.create_destination(
            body={
                "name": f"odoo-repricing-{self.name}",
                "resourceSpecification": {"sqs": {"arn": queue_arn}},
            }
        )
        destination_id = dest.payload["destinationId"]

        api.create_subscription(
            notificationType="ANY_OFFER_CHANGED",
            body={
                "payloadVersion": "1.0",
                "destinationId": destination_id,
            },
        )

        _logger.info(
            "ANY_OFFER_CHANGED subscription created for backend %s (destination %s)",
            self.name,
            destination_id,
        )
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": "Notifications Active",
                "message": (
                    "SQS subscription registered. Messages arrive within ~5 minutes."
                ),
                "type": "success",
            },
        }

    # ── SQS polling ───────────────────────────────────────────────────────────

    def poll_offer_notifications(self):
        """Cron entry point — enqueue a drain job per enabled backend."""
        for backend in self.filtered(
            lambda b: b.notifications_enabled and b.sqs_queue_url
        ):
            backend.with_delay(
                description=f"Drain SQS offer notifications for {backend.name}"
            )._drain_sqs_queue()

    def _drain_sqs_queue(self):
        """Receive and process all pending ANY_OFFER_CHANGED messages."""
        self.ensure_one()
        sqs = self._get_sqs_client()
        processed = 0

        while True:
            resp = sqs.receive_message(
                QueueUrl=self.sqs_queue_url,
                MaxNumberOfMessages=_SQS_MAX_MESSAGES,
                WaitTimeSeconds=0,
            )
            messages = resp.get("Messages", [])
            if not messages:
                break
            for msg in messages:
                try:
                    self._process_offer_notification(json.loads(msg["Body"]))
                    sqs.delete_message(
                        QueueUrl=self.sqs_queue_url,
                        ReceiptHandle=msg["ReceiptHandle"],
                    )
                    processed += 1
                except Exception as exc:
                    _logger.warning(
                        "failed to process SQS message %s on backend %s: %s",
                        msg.get("MessageId"),
                        self.name,
                        exc,
                    )

        _logger.info(
            "processed %d offer notifications for backend %s", processed, self.name
        )

    # ── Notification parsing ──────────────────────────────────────────────────

    def _process_offer_notification(self, payload):
        """Parse one ANY_OFFER_CHANGED payload and update the matching listing.

        Amazon payload structure (payloadVersion 1.0):
          payload.AnyOfferChangedNotification.OfferChangeTrigger.ASIN
          payload.AnyOfferChangedNotification.Summary.BuyBoxPrices[0].ListingPrice.Amount
          payload.AnyOfferChangedNotification.Offers[].{SellerId, IsBuyBoxWinner}
        """
        notification = payload.get("payload", {}).get("AnyOfferChangedNotification", {})
        asin = notification.get("OfferChangeTrigger", {}).get("ASIN")
        if not asin:
            return

        summary = notification.get("Summary", {})
        buy_box_prices = summary.get("BuyBoxPrices", [])
        if not buy_box_prices:
            _logger.debug("no buy box prices in notification for ASIN %s", asin)
            return

        buy_box_price = float(
            buy_box_prices[0].get("ListingPrice", {}).get("Amount", 0)
        )

        # Determine if our seller's offer currently holds the buy box.
        offers = notification.get("Offers", [])
        our_offer = next(
            (o for o in offers if o.get("SellerId") == self.seller_id),
            None,
        )
        buy_box_winner = (
            "us" if our_offer and our_offer.get("IsBuyBoxWinner") else "competitor"
        )

        listing = self.amz_listing_ids.filtered(lambda lst: lst.asin == asin)
        if not listing:
            _logger.debug(
                "ASIN %s not in any listing for backend %s; skipping", asin, self.name
            )
            return

        listing.write(
            {
                "buy_box_price": buy_box_price,
                "buy_box_winner": buy_box_winner,
                "last_price_pull_date": fields.Datetime.now(),
            }
        )
        self._snapshot_offers(listing, offers)

        if self.price_push_enabled:
            self._reprice_listing(listing)

    def _snapshot_offers(self, listing, offers):
        """Persist a competitor-offer snapshot per offer for win-rate analytics."""
        vals_list = []
        for offer in offers:
            seller_id = offer.get("SellerId")
            vals_list.append(
                {
                    "listing_id": listing.id,
                    "seller_id": seller_id,
                    "is_own_offer": bool(seller_id) and seller_id == self.seller_id,
                    "is_buy_box_winner": bool(offer.get("IsBuyBoxWinner")),
                    "price": float(offer.get("ListingPrice", {}).get("Amount", 0) or 0),
                }
            )
        if vals_list:
            self.env["amz.offer.snapshot"].create(vals_list)

    # ── Competitive repricing ─────────────────────────────────────────────────

    def _reprice_listing(self, listing):
        """Compute and push a new price for a single listing if it has changed."""
        new_price = self._compute_listing_price(listing)
        if new_price is None:
            return
        listing.write({"computed_target_price": new_price})
        if new_price == listing.current_list_price:
            return
        self.with_delay(
            description=f"Reprice {listing.seller_sku} on {self.name}"
        )._push_single_listing(listing.id, new_price)

    def _push_single_listing(self, listing_id, price):
        """Push a pre-computed price for one listing."""
        self.ensure_one()
        listing = self.env["amz.listing"].browse(listing_id)
        if not listing.exists():
            return
        from sp_api.api import ListingsItems

        api = self._get_api(ListingsItems)
        try:
            self._patch_listing_price_to_api(api, listing, price)
            listing._log_price_change(price, "notification")
            listing.write(
                {
                    "current_list_price": price,
                    "last_price_push_date": fields.Datetime.now(),
                }
            )
            _logger.info(
                "repriced %s → %.2f on backend %s", listing.seller_sku, price, self.name
            )
        except Exception as exc:
            _logger.warning(
                "reprice push failed for SKU %s on backend %s: %s",
                listing.seller_sku,
                self.name,
                exc,
            )
