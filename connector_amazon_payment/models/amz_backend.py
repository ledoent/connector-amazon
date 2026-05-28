import datetime
import logging

from odoo import fields, models

_logger = logging.getLogger(__name__)


def _parse_amz_dt(value):
    """Parse an Amazon ISO 8601 datetime string into a Python datetime."""
    if not value:
        return False
    if value.endswith("Z"):
        value = value[:-1]
    return datetime.datetime.fromisoformat(value)


class AmazonBackend(models.Model):
    _inherit = "amz.backend"

    amazon_income_account_id = fields.Many2one(
        "account.account",
        "Amazon Income Account",
        help="Revenue account credited for Amazon sales in settlement entries.",
    )
    amazon_fee_account_id = fields.Many2one(
        "account.account",
        "Amazon Fee Account",
        help="Expense account for referral fees, FBA fees, and service fees.",
    )
    amazon_advertising_account_id = fields.Many2one(
        "account.account",
        "Amazon Advertising Account",
        help="Expense account for Amazon Advertising fees.",
    )
    amazon_settlement_journal_id = fields.Many2one(
        "account.journal",
        "Settlement Journal",
        domain=[("type", "in", ["bank", "general"])],
        help="Journal used for Amazon settlement disbursement entries.",
    )
    last_settlement_sync_date = fields.Datetime("Last Settlement Sync", readonly=True)
    amz_settlement_group_ids = fields.One2many(
        "amz.settlement.group", "backend_id", "Settlement Groups"
    )

    def action_sync_settlements(self):
        """Queue a settlement pull job for this backend."""
        self.ensure_one()
        self.with_delay(
            description=f"Sync settlements for {self.name}"
        )._pull_settlements()
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": "Sync Queued",
                "message": "Settlement pull has been queued.",
                "type": "info",
            },
        }

    def _pull_settlements(self):
        """Pull closed settlement groups from Amazon Finances API."""
        self.ensure_one()
        from sp_api.api import Finances

        api = self._get_api(Finances)
        since = self.last_settlement_sync_date or (
            fields.Datetime.now() - datetime.timedelta(days=90)
        )
        next_token = None
        while True:
            kwargs = {
                "FinancialEventGroupStartedAfter": since.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "MaxResults": 100,
            }
            if next_token:
                kwargs["NextToken"] = next_token
            result = api.list_financial_event_groups(**kwargs)
            payload = result.payload
            for group_data in payload.get("FinancialEventGroupList", []):
                if group_data.get("ProcessingStatus") == "Closed":
                    try:
                        self._process_settlement_group(api, group_data)
                    except Exception as exc:
                        _logger.warning(
                            "settlement group %s processing failed on backend %s: %s",
                            group_data.get("FinancialEventGroupId"),
                            self.name,
                            exc,
                        )
            next_token = result.next_token
            if not next_token:
                break
        self.last_settlement_sync_date = fields.Datetime.now()

    def _process_settlement_group(self, api, group_data):
        """Upsert one settlement group, pull its events, and create a journal entry."""
        group_id = group_data["FinancialEventGroupId"]
        existing = self.env["amz.settlement.group"].search(
            [("backend_id", "=", self.id), ("amazon_group_id", "=", group_id)],
            limit=1,
        )
        if existing and existing.account_move_id:
            return

        conv = group_data.get("ConvertedTotal", {})
        orig = group_data.get("OriginalTotal", {})
        currency = self.env["res.currency"].search(
            [("name", "=", conv.get("CurrencyCode", "USD"))], limit=1
        )
        vals = {
            "backend_id": self.id,
            "amazon_group_id": group_id,
            "processing_status": group_data.get("ProcessingStatus"),
            "fund_transfer_date": _parse_amz_dt(group_data.get("FundTransferDate")),
            "original_total": float(orig.get("Amount", 0)),
            "converted_total": float(conv.get("Amount", 0)),
            "currency_id": currency.id,
        }
        if existing:
            existing.write(vals)
            group = existing
        else:
            group = self.env["amz.settlement.group"].create(vals)

        group.financial_event_ids.unlink()
        self._pull_group_events(api, group)
        self._create_settlement_entry(group)

    def _pull_group_events(self, api, group):
        """Fetch and parse all financial events for a settlement group."""
        next_token = None
        while True:
            kwargs = {"MaxResults": 100}
            if next_token:
                kwargs["NextToken"] = next_token
            result = api.list_financial_events_by_group_id(
                group.amazon_group_id, **kwargs
            )
            fe = result.payload.get("FinancialEvents", {})
            self._parse_shipment_events(group, fe.get("ShipmentEvents", []))
            self._parse_refund_events(group, fe.get("RefundEvents", []))
            self._parse_service_fee_events(group, fe.get("ServiceFeeEvents", []))
            self._parse_advertising_events(group, fe.get("AdvertisingFeeEvents", []))
            next_token = result.next_token
            if not next_token:
                break

    def _parse_shipment_events(self, group, events):
        """Aggregate Principal, Commission, and FBA fees per ShipmentEvent."""
        Event = self.env["amz.financial.event"]
        for event in events:
            order_id = event.get("AmazonOrderId")
            posted_date = _parse_amz_dt(event.get("PostedDate"))
            principal = commission = fba = 0.0
            for item in event.get("ShipmentItemList", []):
                for charge in item.get("ItemChargeList", []):
                    if charge.get("ChargeType") == "Principal":
                        principal += float(
                            charge.get("ChargeAmount", {}).get("Amount", 0)
                        )
                for fee in item.get("ItemFeeList", []):
                    fee_type = fee.get("FeeType", "")
                    amount = float(fee.get("FeeAmount", {}).get("Amount", 0))
                    if fee_type == "Commission":
                        commission += amount
                    elif "FBA" in fee_type or "Fulfillment" in fee_type:
                        fba += amount
            base = {
                "settlement_group_id": group.id,
                "amz_order_id": order_id,
                "posted_date": posted_date,
            }
            if principal:
                Event.create(
                    {
                        **base,
                        "event_type": "shipment",
                        "amount": principal,
                        "fee_description": "Principal",
                    }
                )
            if commission:
                Event.create(
                    {
                        **base,
                        "event_type": "referral_fee",
                        "amount": commission,
                        "fee_description": "Commission",
                    }
                )
            if fba:
                Event.create(
                    {
                        **base,
                        "event_type": "fba_fee",
                        "amount": fba,
                        "fee_description": "FBAFee",
                    }
                )

    def _parse_refund_events(self, group, events):
        """Aggregate Principal charges from RefundEvents."""
        Event = self.env["amz.financial.event"]
        for event in events:
            order_id = event.get("AmazonOrderId")
            posted_date = _parse_amz_dt(event.get("PostedDate"))
            total = 0.0
            for item in event.get("ShipmentItemAdjustmentList", []):
                for charge in item.get("ItemChargeAdjustmentList", []):
                    if charge.get("ChargeType") == "Principal":
                        total += float(charge.get("ChargeAmount", {}).get("Amount", 0))
            if total:
                Event.create(
                    {
                        "settlement_group_id": group.id,
                        "event_type": "refund",
                        "amz_order_id": order_id,
                        "posted_date": posted_date,
                        "amount": total,
                        "fee_description": "Refund",
                    }
                )

    def _parse_fee_events(
        self, group, events, event_type, default_description, description_key=None
    ):
        """Create one financial event per fee event."""
        Event = self.env["amz.financial.event"]
        for event in events:
            posted_date = _parse_amz_dt(event.get("PostedDate"))
            total = sum(
                float(f.get("FeeAmount", {}).get("Amount", 0))
                for f in event.get("FeeList", [])
            )
            if total:
                desc = (
                    event.get(description_key, default_description)
                    if description_key
                    else default_description
                )
                Event.create(
                    {
                        "settlement_group_id": group.id,
                        "event_type": event_type,
                        "posted_date": posted_date,
                        "amount": total,
                        "fee_description": desc,
                    }
                )

    def _parse_service_fee_events(self, group, events):
        """Create one service_fee event per ServiceFeeEvent."""
        self._parse_fee_events(group, events, "service_fee", "ServiceFee", "FeeReason")

    def _parse_advertising_events(self, group, events):
        """Create one advertising event per AdvertisingFeeEvent."""
        self._parse_fee_events(group, events, "advertising", "AdvertisingFee")

    def _create_settlement_entry(self, group):
        """Generate a journal entry for a closed settlement group."""
        if not self.amazon_settlement_journal_id:
            _logger.warning(
                "no settlement journal configured for backend %s; skipping entry",
                self.name,
            )
            return

        events = group.financial_event_ids
        income = sum(e.amount for e in events if e.amount > 0)
        adv_fees = abs(
            sum(
                e.amount
                for e in events
                if e.event_type == "advertising" and e.amount < 0
            )
        )
        other_fees = abs(
            sum(
                e.amount
                for e in events
                if e.event_type != "advertising" and e.amount < 0
            )
        )
        net = group.converted_total
        entry_date = (
            group.fund_transfer_date.date()
            if group.fund_transfer_date
            else fields.Date.today()
        )

        lines = []
        if income and self.amazon_income_account_id:
            lines.append(
                (
                    0,
                    0,
                    {
                        "account_id": self.amazon_income_account_id.id,
                        "name": f"Amazon sales — {group.amazon_group_id}",
                        "credit": income,
                    },
                )
            )
        if other_fees and self.amazon_fee_account_id:
            lines.append(
                (
                    0,
                    0,
                    {
                        "account_id": self.amazon_fee_account_id.id,
                        "name": f"Amazon fees — {group.amazon_group_id}",
                        "debit": other_fees,
                    },
                )
            )
        if adv_fees:
            adv_account = (
                self.amazon_advertising_account_id or self.amazon_fee_account_id
            )
            if adv_account:
                lines.append(
                    (
                        0,
                        0,
                        {
                            "account_id": adv_account.id,
                            "name": f"Amazon advertising — {group.amazon_group_id}",
                            "debit": adv_fees,
                        },
                    )
                )
        lines.append(
            (
                0,
                0,
                {
                    "account_id": (
                        self.amazon_settlement_journal_id.default_account_id.id
                    ),
                    "name": f"Amazon disbursement — {group.amazon_group_id}",
                    "debit": net,
                },
            )
        )

        move = self.env["account.move"].create(
            {
                "journal_id": self.amazon_settlement_journal_id.id,
                "date": entry_date,
                "ref": f"Amazon Settlement {group.amazon_group_id}",
                "line_ids": lines,
                "move_type": "entry",
            }
        )
        move.action_post()
        group.account_move_id = move

    def sync_settlements(self):
        """Cron entry point — enqueue settlement pull for each active backend."""
        for backend in self.filtered("active"):
            backend.with_delay(
                description=f"Sync settlements for {backend.name}"
            )._pull_settlements()
