import datetime
import logging

from odoo import fields, models

_logger = logging.getLogger(__name__)

# Amazon ItemChargeList ChargeType → our event_type bucket. Charge types not
# listed here (e.g. Principal, handled separately) are ignored.
_CHARGE_TYPE_TO_EVENT = {
    "Tax": "tax",
    "ShippingTax": "tax",
    "GiftWrapTax": "tax",
    "ShippingCharge": "shipping",
    "GiftWrap": "shipping",
}


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
    amazon_tax_account_id = fields.Many2one(
        "account.account",
        "Amazon Tax Account",
        help="Liability account for sales tax. Marketplace Facilitator Tax that "
        "Amazon collects and remits nets to zero here; only seller-liable tax "
        "leaves a balance.",
    )
    amazon_shipping_account_id = fields.Many2one(
        "account.account",
        "Amazon Shipping Account",
        help="Revenue account for shipping and gift-wrap charged to the buyer.",
    )
    amazon_promotion_account_id = fields.Many2one(
        "account.account",
        "Amazon Promotion Account",
        help="Contra-revenue account for seller-funded promotions and coupons.",
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
        from sp_api.base import SellingApiException

        api = self._get_api(Finances)
        since = self.last_settlement_sync_date or (
            fields.Datetime.now() - datetime.timedelta(days=90)
        )
        next_token = None
        try:
            while True:
                kwargs = {
                    "FinancialEventGroupStartedAfter": since.strftime(
                        "%Y-%m-%dT%H:%M:%SZ"
                    ),
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
                                "settlement group %s failed on backend %s: %s",
                                group_data.get("FinancialEventGroupId"),
                                self.name,
                                exc,
                            )
                next_token = result.next_token
                if not next_token:
                    break
        except SellingApiException as exc:
            _logger.error(
                "Amazon Finances API failed for backend %s: %s", self.name, exc
            )
            raise
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
        self._reconcile_settlement(group)

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
        """Aggregate per ShipmentEvent: Principal/Commission/FBA plus tax
        (collected and Amazon-withheld), shipping, and promotions."""
        self._parse_shipment_like(
            group,
            events,
            item_key="ShipmentItemList",
            charge_key="ItemChargeList",
            promotion_key="PromotionList",
            sign=1.0,
        )

    def _parse_refund_events(self, group, events):
        """RefundEvents mirror ShipmentEvents (adjustment lists, sign flipped):
        Principal becomes a refund, fees/tax/shipping/promo reverse."""
        self._parse_shipment_like(
            group,
            events,
            item_key="ShipmentItemAdjustmentList",
            charge_key="ItemChargeAdjustmentList",
            promotion_key="PromotionAdjustmentList",
            sign=-1.0,
            principal_event="refund",
        )

    def _parse_shipment_like(
        self,
        group,
        events,
        item_key,
        charge_key,
        promotion_key,
        sign,
        principal_event="shipment",
    ):
        """Shared parser for ShipmentEvents and RefundEvents.

        ``sign`` is +1 for shipments and -1 for refunds (adjustment amounts are
        positive in the payload but represent reversals). ``principal_event``
        routes Principal to ``shipment`` or ``refund``.
        """
        vals_list = []
        for event in events:
            order_id = event.get("AmazonOrderId")
            posted_date = _parse_amz_dt(event.get("PostedDate"))
            buckets = {}  # event_type → (amount, description)
            for item in event.get(item_key, []):
                for charge in item.get(charge_key, []):
                    ctype = charge.get("ChargeType", "")
                    amount = sign * float(
                        charge.get("ChargeAmount", {}).get("Amount", 0)
                    )
                    if ctype == "Principal":
                        evt, desc = principal_event, "Principal"
                    elif ctype in _CHARGE_TYPE_TO_EVENT:
                        evt, desc = _CHARGE_TYPE_TO_EVENT[ctype], ctype
                    else:
                        continue
                    acc, _d = buckets.get(evt, (0.0, desc))
                    buckets[evt] = (acc + amount, desc)
                # Marketplace Facilitator Tax that Amazon collects then withholds
                # (negative) nets against collected Tax above → tax washes to 0.
                for withheld in item.get("ItemTaxWithheldList", []):
                    for charge in withheld.get("TaxesWithheld", []):
                        amount = sign * float(
                            charge.get("ChargeAmount", {}).get("Amount", 0)
                        )
                        acc, _d = buckets.get("tax", (0.0, "TaxWithheld"))
                        buckets["tax"] = (acc + amount, "Tax")
                for fee in item.get("ItemFeeList", []):
                    fee_type = fee.get("FeeType", "")
                    amount = sign * float(fee.get("FeeAmount", {}).get("Amount", 0))
                    if fee_type == "Commission":
                        evt, desc = "referral_fee", "Commission"
                    elif "FBA" in fee_type or "Fulfillment" in fee_type:
                        evt, desc = "fba_fee", "FBAFee"
                    else:
                        continue
                    acc, _d = buckets.get(evt, (0.0, desc))
                    buckets[evt] = (acc + amount, desc)
                for promo in item.get(promotion_key, []):
                    amount = sign * float(
                        promo.get("PromotionAmount", {}).get("Amount", 0)
                    )
                    acc, _d = buckets.get("promotion", (0.0, "Promotion"))
                    buckets["promotion"] = (acc + amount, "Promotion")
            for evt, (amount, desc) in buckets.items():
                if amount:
                    vals_list.append(
                        {
                            "settlement_group_id": group.id,
                            "amz_order_id": order_id,
                            "posted_date": posted_date,
                            "event_type": evt,
                            "amount": amount,
                            "fee_description": desc,
                        }
                    )
        if vals_list:
            self.env["amz.financial.event"].create(vals_list)

    def _parse_fee_events(
        self, group, events, event_type, default_description, description_key=None
    ):
        """Create one financial event per fee event."""
        vals_list = []
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
                vals_list.append(
                    {
                        "settlement_group_id": group.id,
                        "event_type": event_type,
                        "posted_date": posted_date,
                        "amount": total,
                        "fee_description": desc,
                    }
                )
        if vals_list:
            self.env["amz.financial.event"].create(vals_list)

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
        disbursement_account = self.amazon_settlement_journal_id.default_account_id
        if not disbursement_account:
            _logger.warning(
                "settlement journal %s has no default account on backend %s; "
                "skipping entry",
                self.amazon_settlement_journal_id.name,
                self.name,
            )
            return

        entry_date = (
            group.fund_transfer_date.date()
            if group.fund_transfer_date
            else fields.Date.today()
        )

        # Sum the settlement's financial events by type, then post each modeled
        # bucket to its own GL account. Net signed total per type: positive =
        # money in (credit revenue), negative = money out (debit expense/contra).
        fee_account = self.amazon_fee_account_id
        income_account = self.amazon_income_account_id
        # event_type → (account, label). Sign of the summed amount decides the
        # debit/credit side, so each type's line is correct whichever way it nets.
        type_accounts = {
            "shipment": (income_account, "Amazon sales"),
            "refund": (income_account, "Amazon refunds"),
            "shipping": (
                self.amazon_shipping_account_id or income_account,
                "Amazon shipping",
            ),
            "promotion": (
                self.amazon_promotion_account_id or income_account,
                "Amazon promotions",
            ),
            "tax": (self.amazon_tax_account_id, "Amazon tax"),
            "referral_fee": (fee_account, "Amazon referral fees"),
            "fba_fee": (fee_account, "Amazon FBA fees"),
            "service_fee": (fee_account, "Amazon service fees"),
            "advertising": (
                self.amazon_advertising_account_id or fee_account,
                "Amazon advertising",
            ),
            "other": (fee_account, "Amazon other"),
        }
        currency = group.currency_id or self.env.company.currency_id
        totals = {}
        for event in group.financial_event_ids:
            totals[event.event_type] = totals.get(event.event_type, 0.0) + event.amount

        lines = []
        for event_type, amount in totals.items():
            amount = currency.round(amount)
            if currency.is_zero(amount):
                continue  # e.g. Marketplace Facilitator Tax washes to zero
            account = type_accounts.get(event_type, (fee_account, "Amazon other"))[0]
            label = type_accounts.get(event_type, (None, "Amazon other"))[1]
            if not account:
                continue  # unconfigured optional account → absorbed by the plug
            line = {
                "account_id": account.id,
                "name": f"{label} — {group.amazon_group_id}",
            }
            # amount > 0 → revenue/credit; amount < 0 → expense/debit
            line["credit" if amount > 0 else "debit"] = abs(amount)
            lines.append((0, 0, line))

        # Disbursement: the actual cash Amazon transferred (debit the bank/journal
        # account). Booked at converted_total even when modeled buckets don't sum
        # to it — the adjustment line below absorbs any residual.
        lines.append(
            (
                0,
                0,
                {
                    "account_id": disbursement_account.id,
                    "name": f"Amazon disbursement — {group.amazon_group_id}",
                    "debit": group.converted_total,
                },
            )
        )

        # Residual after modeling tax/shipping/promotions should be only currency
        # rounding. Odoo rejects an unbalanced move at create() time, so book any
        # remainder to an adjustment line — keeps the disbursement intact and never
        # drops the settlement.
        imbalance = currency.round(
            sum(ln[2].get("debit", 0.0) for ln in lines)
            - sum(ln[2].get("credit", 0.0) for ln in lines)
        )
        if not currency.is_zero(imbalance):
            adjustment_account = (
                self.amazon_income_account_id or self.amazon_fee_account_id
            )
            if not adjustment_account:
                _logger.warning(
                    "settlement %s is unbalanced by %s but no income/fee account is "
                    "configured to absorb it; skipping entry",
                    group.amazon_group_id,
                    imbalance,
                )
                return
            adj = {
                "account_id": adjustment_account.id,
                "name": f"Amazon unclassified adjustment — {group.amazon_group_id}",
            }
            # debits exceed credits → balance with a credit, and vice versa
            adj["credit" if imbalance > 0 else "debit"] = abs(imbalance)
            lines.append((0, 0, adj))

        move = self.env["account.move"].create(
            {
                "journal_id": self.amazon_settlement_journal_id.id,
                "date": entry_date,
                "ref": f"Amazon Settlement {group.amazon_group_id}",
                "line_ids": lines,
                "move_type": "entry",
            }
        )
        group.account_move_id = move
        move.action_post()

    def _reconcile_settlement(self, group):
        """Match each order's settled Principal against its posted invoice.

        Builds one ``amz.settlement.reconciliation`` row per Amazon order in the
        group: settled Principal vs the order's posted customer-invoice total,
        flagged ``matched`` / ``variance`` / ``no_invoice``. Idempotent per group.
        """
        Recon = self.env["amz.settlement.reconciliation"]
        currency = group.currency_id or self.env.company.currency_id
        group.reconciliation_ids.unlink()

        settled_by_order = {}
        for event in group.financial_event_ids.filtered(
            lambda e: e.event_type == "shipment" and e.amz_order_id
        ):
            settled_by_order[event.amz_order_id] = (
                settled_by_order.get(event.amz_order_id, 0.0) + event.amount
            )

        vals_list = []
        for amz_order_id, settled in settled_by_order.items():
            order = self.env["amz.order"].search(
                [("backend_id", "=", self.id), ("amz_order_id", "=", amz_order_id)],
                limit=1,
            )
            invoice = self.env["account.move"]
            if order.sale_order_id:
                invoice = order.sale_order_id.invoice_ids.filtered(
                    lambda m: m.move_type == "out_invoice" and m.state == "posted"
                )[:1]
            if invoice:
                invoiced = invoice.amount_untaxed
                variance = currency.round(settled - invoiced)
                state = "matched" if currency.is_zero(variance) else "variance"
            else:
                invoiced = 0.0
                variance = 0.0
                state = "no_invoice"
            vals_list.append(
                {
                    "settlement_group_id": group.id,
                    "amz_order_id": amz_order_id,
                    "order_id": order.id or False,
                    "invoice_id": invoice.id or False,
                    "settled_principal": settled,
                    "invoiced_total": invoiced,
                    "variance": variance,
                    "state": state,
                }
            )
        if vals_list:
            Recon.create(vals_list)

    def sync_settlements(self):
        """Cron entry point — enqueue settlement pull for each active backend."""
        for backend in self.filtered("active"):
            backend.with_delay(
                description=f"Sync settlements for {backend.name}"
            )._pull_settlements()
