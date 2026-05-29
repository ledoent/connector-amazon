from unittest.mock import MagicMock, patch

from odoo import fields
from odoo.tests.common import TransactionCase
from odoo.tools import mute_logger

SANDBOX_GROUP_DATA = {
    "FinancialEventGroupId": "GROUP001",
    "ProcessingStatus": "Closed",
    "OriginalTotal": {"CurrencyCode": "USD", "Amount": "100.00"},
    "ConvertedTotal": {"CurrencyCode": "USD", "Amount": "85.00"},
    "FundTransferDate": "2024-05-01T00:00:00Z",
}

SANDBOX_GROUPS_PAYLOAD = {
    "FinancialEventGroupList": [SANDBOX_GROUP_DATA],
}

SANDBOX_EVENTS_PAYLOAD = {
    "FinancialEvents": {
        "ShipmentEvents": [
            {
                "AmazonOrderId": "123-456-789",
                "PostedDate": "2024-05-01T00:00:00Z",
                "ShipmentItemList": [
                    {
                        "ItemChargeList": [
                            {
                                "ChargeType": "Principal",
                                "ChargeAmount": {
                                    "Amount": "100.00",
                                    "CurrencyCode": "USD",
                                },
                            }
                        ],
                        "ItemFeeList": [
                            {
                                "FeeType": "Commission",
                                "FeeAmount": {
                                    "Amount": "-15.00",
                                    "CurrencyCode": "USD",
                                },
                            }
                        ],
                    }
                ],
            }
        ],
        "RefundEvents": [],
        "ServiceFeeEvents": [],
        "AdvertisingFeeEvents": [],
    }
}


# Principal 100 + Tax 8 + Shipping 5 − Commission 15 − Promotion 3 − TaxWithheld 8
# → seller nets 87 (= ConvertedTotal). Tax washes (8 collected − 8 withheld).
MULTICHARGE_GROUP_DATA = {
    "FinancialEventGroupId": "GROUPMC",
    "ProcessingStatus": "Closed",
    "OriginalTotal": {"CurrencyCode": "USD", "Amount": "87.00"},
    "ConvertedTotal": {"CurrencyCode": "USD", "Amount": "87.00"},
    "FundTransferDate": "2024-05-01T00:00:00Z",
}
MULTICHARGE_GROUPS_PAYLOAD = {"FinancialEventGroupList": [MULTICHARGE_GROUP_DATA]}
MULTICHARGE_EVENTS_PAYLOAD = {
    "FinancialEvents": {
        "ShipmentEvents": [
            {
                "AmazonOrderId": "111-222-333",
                "PostedDate": "2024-05-01T00:00:00Z",
                "ShipmentItemList": [
                    {
                        "ItemChargeList": [
                            {
                                "ChargeType": "Principal",
                                "ChargeAmount": {"Amount": "100.00"},
                            },
                            {"ChargeType": "Tax", "ChargeAmount": {"Amount": "8.00"}},
                            {
                                "ChargeType": "ShippingCharge",
                                "ChargeAmount": {"Amount": "5.00"},
                            },
                        ],
                        "ItemTaxWithheldList": [
                            {
                                "TaxCollectionModel": "MarketplaceFacilitator",
                                "TaxesWithheld": [
                                    {
                                        "ChargeType": "MarketplaceFacilitatorTax",
                                        "ChargeAmount": {"Amount": "-8.00"},
                                    }
                                ],
                            }
                        ],
                        "ItemFeeList": [
                            {"FeeType": "Commission", "FeeAmount": {"Amount": "-15.00"}}
                        ],
                        "PromotionList": [
                            {
                                "PromotionType": "Coupon",
                                "PromotionAmount": {"Amount": "-3.00"},
                            }
                        ],
                    }
                ],
            }
        ],
        "RefundEvents": [],
        "ServiceFeeEvents": [],
        "AdvertisingFeeEvents": [],
    }
}


def _mock_finances_api(groups_payload, events_payload):
    api = MagicMock()

    groups_resp = MagicMock()
    groups_resp.payload = groups_payload
    groups_resp.next_token = None
    api.list_financial_event_groups.return_value = groups_resp

    events_resp = MagicMock()
    events_resp.payload = events_payload
    events_resp.next_token = None
    api.list_financial_events_by_group_id.return_value = events_resp

    return api


class TestPayment(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.backend = cls.env["amz.backend"].create(
            {
                "name": "Test Payment Backend",
                "client_id": "test_client_id",
                "client_secret": "test_secret",
                "refresh_token": "test_token",
                "marketplace_id": "ATVPDKIKX0DER",
                "sandbox": True,
                "warehouse_id": cls.env["stock.warehouse"].search([], limit=1).id,
            }
        )
        cls.usd = cls.env.ref("base.USD")
        # Minimal journal and accounts for journal entry tests
        cls.bank_journal = cls.env["account.journal"].create(
            {
                "name": "Amazon Settlement",
                "type": "bank",
                "code": "AMZB",
            }
        )
        cls.income_account = cls.env["account.account"].create(
            {
                "name": "Amazon Sales",
                "code": "400100",
                "account_type": "income",
            }
        )
        cls.fee_account = cls.env["account.account"].create(
            {
                "name": "Amazon Fees",
                "code": "600100",
                "account_type": "expense",
            }
        )
        cls.tax_account = cls.env["account.account"].create(
            {
                "name": "Amazon Tax",
                "code": "210100",
                "account_type": "liability_current",
            }
        )
        cls.shipping_account = cls.env["account.account"].create(
            {
                "name": "Amazon Shipping",
                "code": "400200",
                "account_type": "income",
            }
        )
        cls.promotion_account = cls.env["account.account"].create(
            {
                "name": "Amazon Promotions",
                "code": "400300",
                "account_type": "income",
            }
        )

    def _configure_backend(self):
        self.backend.write(
            {
                "amazon_settlement_journal_id": self.bank_journal.id,
                "amazon_income_account_id": self.income_account.id,
                "amazon_fee_account_id": self.fee_account.id,
                "amazon_tax_account_id": self.tax_account.id,
                "amazon_shipping_account_id": self.shipping_account.id,
                "amazon_promotion_account_id": self.promotion_account.id,
            }
        )

    # ── test 1: group creation ────────────────────────────────────────────────

    def test_pull_settlements_creates_group(self):
        self._configure_backend()
        api = _mock_finances_api(SANDBOX_GROUPS_PAYLOAD, SANDBOX_EVENTS_PAYLOAD)

        with patch.object(type(self.backend), "_get_api", return_value=api):
            self.backend._pull_settlements()

        group = self.env["amz.settlement.group"].search(
            [("backend_id", "=", self.backend.id), ("amazon_group_id", "=", "GROUP001")]
        )
        self.assertEqual(len(group), 1)
        self.assertAlmostEqual(group.converted_total, 85.00, places=2)
        self.assertAlmostEqual(group.original_total, 100.00, places=2)
        self.assertEqual(group.processing_status, "Closed")

    # ── test 2: open groups skipped ───────────────────────────────────────────

    def test_pull_settlements_skips_open_groups(self):
        self._configure_backend()
        open_payload = {
            "FinancialEventGroupList": [
                {
                    **SANDBOX_GROUP_DATA,
                    "FinancialEventGroupId": "OPEN001",
                    "ProcessingStatus": "Open",
                }
            ]
        }
        api = _mock_finances_api(open_payload, SANDBOX_EVENTS_PAYLOAD)

        with patch.object(type(self.backend), "_get_api", return_value=api):
            self.backend._pull_settlements()

        group = self.env["amz.settlement.group"].search(
            [("backend_id", "=", self.backend.id), ("amazon_group_id", "=", "OPEN001")]
        )
        self.assertFalse(group)

    # ── test 3: idempotency ───────────────────────────────────────────────────

    def test_pull_settlements_idempotent(self):
        """Second pull must not create a duplicate group or duplicate journal entry."""
        self._configure_backend()
        api = _mock_finances_api(SANDBOX_GROUPS_PAYLOAD, SANDBOX_EVENTS_PAYLOAD)

        with patch.object(type(self.backend), "_get_api", return_value=api):
            self.backend._pull_settlements()
            self.backend._pull_settlements()

        groups = self.env["amz.settlement.group"].search(
            [("backend_id", "=", self.backend.id), ("amazon_group_id", "=", "GROUP001")]
        )
        self.assertEqual(len(groups), 1)
        # API should only have been called twice total for events (once per pull,
        # but second pull skips because account_move_id is already set)
        self.assertEqual(api.list_financial_events_by_group_id.call_count, 1)

    # ── test 4: pagination ────────────────────────────────────────────────────

    @mute_logger("odoo.addons.connector_amazon_payment.models.amz_backend")
    def test_pull_settlements_follows_pagination(self):
        # No journal configured — just verify pagination mechanics, not accounting
        page1_resp = MagicMock()
        page1_resp.payload = {
            "FinancialEventGroupList": [SANDBOX_GROUP_DATA],
        }
        page1_resp.next_token = "page2_token"

        page2_data = {
            **SANDBOX_GROUP_DATA,
            "FinancialEventGroupId": "GROUP002",
            "ConvertedTotal": {"CurrencyCode": "USD", "Amount": "50.00"},
            "OriginalTotal": {"CurrencyCode": "USD", "Amount": "60.00"},
        }
        page2_resp = MagicMock()
        page2_resp.payload = {"FinancialEventGroupList": [page2_data]}
        page2_resp.next_token = None

        events_resp = MagicMock()
        events_resp.payload = SANDBOX_EVENTS_PAYLOAD
        events_resp.next_token = None

        api = MagicMock()
        api.list_financial_event_groups.side_effect = [page1_resp, page2_resp]
        api.list_financial_events_by_group_id.return_value = events_resp

        with patch.object(type(self.backend), "_get_api", return_value=api):
            self.backend._pull_settlements()

        self.assertEqual(api.list_financial_event_groups.call_count, 2)
        second_call_kwargs = api.list_financial_event_groups.call_args_list[1].kwargs
        self.assertEqual(second_call_kwargs.get("NextToken"), "page2_token")

        groups = self.env["amz.settlement.group"].search(
            [("backend_id", "=", self.backend.id)]
        )
        self.assertEqual(len(groups), 2)

    # ── test 5: financial event parsing ──────────────────────────────────────

    def test_parse_events_creates_financial_events(self):
        self._configure_backend()
        api = _mock_finances_api(SANDBOX_GROUPS_PAYLOAD, SANDBOX_EVENTS_PAYLOAD)

        with patch.object(type(self.backend), "_get_api", return_value=api):
            self.backend._pull_settlements()

        group = self.env["amz.settlement.group"].search(
            [("backend_id", "=", self.backend.id), ("amazon_group_id", "=", "GROUP001")]
        )
        events = group.financial_event_ids
        shipment = events.filtered(lambda e: e.event_type == "shipment")
        referral = events.filtered(lambda e: e.event_type == "referral_fee")

        self.assertTrue(shipment)
        self.assertAlmostEqual(shipment.amount, 100.00, places=2)
        self.assertEqual(shipment.amz_order_id, "123-456-789")

        self.assertTrue(referral)
        self.assertAlmostEqual(referral.amount, -15.00, places=2)

    # ── test 6: journal entry debit/credit ───────────────────────────────────

    def test_create_settlement_entry_dr_cr(self):
        self._configure_backend()
        api = _mock_finances_api(SANDBOX_GROUPS_PAYLOAD, SANDBOX_EVENTS_PAYLOAD)

        with patch.object(type(self.backend), "_get_api", return_value=api):
            self.backend._pull_settlements()

        group = self.env["amz.settlement.group"].search(
            [("backend_id", "=", self.backend.id), ("amazon_group_id", "=", "GROUP001")]
        )
        self.assertTrue(group.account_move_id)
        move = group.account_move_id
        self.assertEqual(move.state, "posted")

        credit_lines = move.line_ids.filtered(lambda ln: ln.credit > 0)
        debit_lines = move.line_ids.filtered(lambda ln: ln.debit > 0)
        self.assertTrue(credit_lines)
        self.assertTrue(debit_lines)
        # Total debits == total credits (balanced entry)
        self.assertAlmostEqual(
            sum(credit_lines.mapped("credit")),
            sum(debit_lines.mapped("debit")),
            places=2,
        )

    # ── test 7: no journal → no entry ────────────────────────────────────────

    @mute_logger("odoo.addons.connector_amazon_payment.models.amz_backend")
    def test_create_settlement_entry_skips_without_journal(self):
        # Backend has no settlement journal
        api = _mock_finances_api(SANDBOX_GROUPS_PAYLOAD, SANDBOX_EVENTS_PAYLOAD)

        with patch.object(type(self.backend), "_get_api", return_value=api):
            self.backend._pull_settlements()

        group = self.env["amz.settlement.group"].search(
            [("backend_id", "=", self.backend.id), ("amazon_group_id", "=", "GROUP001")]
        )
        self.assertTrue(group)
        self.assertFalse(group.account_move_id)

    # ── test 8: action_sync_settlements queues job ────────────────────────────

    # ── test 9: last_settlement_sync_date updated ─────────────────────────────

    def test_pull_settlements_updates_last_sync_date(self):
        self.assertFalse(self.backend.last_settlement_sync_date)
        api = _mock_finances_api({"FinancialEventGroupList": []}, {})

        with patch.object(type(self.backend), "_get_api", return_value=api):
            self.backend._pull_settlements()

        self.backend.invalidate_recordset()
        self.assertTrue(self.backend.last_settlement_sync_date)

    # ── test 10: batch error resilience ──────────────────────────────────────

    @mute_logger("odoo.addons.connector_amazon_payment.models.amz_backend")
    def test_pull_settlements_continues_after_group_error(self):
        """One failing group must not abort processing of subsequent groups."""
        self._configure_backend()
        good_data = {**SANDBOX_GROUP_DATA, "FinancialEventGroupId": "GOOD001"}
        payload = {
            "FinancialEventGroupList": [
                {**SANDBOX_GROUP_DATA, "FinancialEventGroupId": "BAD001"},
                good_data,
            ]
        }
        api = _mock_finances_api(payload, SANDBOX_EVENTS_PAYLOAD)

        original_process = type(self.backend)._process_settlement_group

        def selective_fail(self_inner, inner_api, group_data):
            if group_data.get("FinancialEventGroupId") == "BAD001":
                raise ValueError("Simulated failure")
            return original_process(self_inner, inner_api, group_data)

        with patch.object(
            type(self.backend), "_process_settlement_group", selective_fail
        ):
            with patch.object(type(self.backend), "_get_api", return_value=api):
                self.backend._pull_settlements()

        good = self.env["amz.settlement.group"].search(
            [("backend_id", "=", self.backend.id), ("amazon_group_id", "=", "GOOD001")]
        )
        self.assertTrue(good)

    # ── test 11: advertising account used for advertising events ──────────────

    def test_create_settlement_entry_advertising_account(self):
        """Advertising events must debit amazon_advertising_account_id when set."""
        adv_account = self.env["account.account"].create(
            {
                "name": "Amazon Advertising Expense",
                "code": "700100",
                "account_type": "expense",
            }
        )
        self._configure_backend()
        self.backend.amazon_advertising_account_id = adv_account

        usd = self.env.ref("base.USD")
        group = self.env["amz.settlement.group"].create(
            {
                "backend_id": self.backend.id,
                "amazon_group_id": "ADVGROUP001",
                "processing_status": "Closed",
                "fund_transfer_date": fields.Datetime.now(),
                "original_total": 80.00,
                "converted_total": 80.00,
                "currency_id": usd.id,
            }
        )
        # income=100, referral=-15, advertising=-5 → net=80 (balanced)
        self.env["amz.financial.event"].create(
            [
                {
                    "settlement_group_id": group.id,
                    "event_type": "shipment",
                    "amount": 100.00,
                },
                {
                    "settlement_group_id": group.id,
                    "event_type": "referral_fee",
                    "amount": -15.00,
                },
                {
                    "settlement_group_id": group.id,
                    "event_type": "advertising",
                    "amount": -5.00,
                },
            ]
        )

        self.backend._create_settlement_entry(group)

        self.assertTrue(group.account_move_id)
        adv_lines = group.account_move_id.line_ids.filtered(
            lambda ln: ln.account_id == adv_account
        )
        self.assertTrue(adv_lines)
        self.assertAlmostEqual(adv_lines.debit, 5.00, places=2)

    # ── test 12: unmodeled charges absorbed by adjustment line ────────────────

    @mute_logger("odoo.addons.connector_amazon_payment.models.amz_backend")
    def test_create_settlement_entry_balances_with_adjustment(self):
        """When converted_total != modeled income - fees (e.g. tax/shipping not
        modeled), the move must still balance and post via an adjustment line —
        Odoo rejects unbalanced moves at create() time, so the gap is booked, not
        dropped."""
        self._configure_backend()
        usd = self.env.ref("base.USD")
        # income=100, fee=-15 → modeled net=85, but Amazon disbursed 95 (e.g.
        # tax collected not modeled here) → 10.00 unclassified gap.
        group = self.env["amz.settlement.group"].create(
            {
                "backend_id": self.backend.id,
                "amazon_group_id": "UNBAL001",
                "processing_status": "Closed",
                "fund_transfer_date": fields.Datetime.now(),
                "original_total": 95.00,
                "converted_total": 95.00,
                "currency_id": usd.id,
            }
        )
        self.env["amz.financial.event"].create(
            [
                {
                    "settlement_group_id": group.id,
                    "event_type": "shipment",
                    "amount": 100.00,
                },
                {
                    "settlement_group_id": group.id,
                    "event_type": "referral_fee",
                    "amount": -15.00,
                },
            ]
        )

        # Must not raise even though the modeled components don't balance.
        self.backend._create_settlement_entry(group)

        move = group.account_move_id
        self.assertTrue(move, "move must be created")
        self.assertEqual(move.state, "posted")
        self.assertAlmostEqual(
            sum(move.line_ids.mapped("debit")),
            sum(move.line_ids.mapped("credit")),
            places=2,
        )
        adj = move.line_ids.filtered(lambda ln: "unclassified" in (ln.name or ""))
        self.assertTrue(
            adj, "the unclassified gap must be booked to an adjustment line"
        )
        self.assertAlmostEqual(adj.credit - adj.debit, 10.00, places=2)

    # ── test 13: journal without default account → no entry ───────────────────

    @mute_logger("odoo.addons.connector_amazon_payment.models.amz_backend")
    def test_create_settlement_entry_skips_journal_without_default_account(self):
        """A general journal with no default account must not crash; skip entry."""
        no_acct_journal = self.env["account.journal"].create(
            {"name": "No Default Acct", "type": "general", "code": "AMZNA"}
        )
        no_acct_journal.default_account_id = False
        self.backend.write(
            {
                "amazon_settlement_journal_id": no_acct_journal.id,
                "amazon_income_account_id": self.income_account.id,
                "amazon_fee_account_id": self.fee_account.id,
            }
        )
        usd = self.env.ref("base.USD")
        group = self.env["amz.settlement.group"].create(
            {
                "backend_id": self.backend.id,
                "amazon_group_id": "NOACCT001",
                "processing_status": "Closed",
                "converted_total": 85.00,
                "currency_id": usd.id,
            }
        )
        self.env["amz.financial.event"].create(
            {
                "settlement_group_id": group.id,
                "event_type": "shipment",
                "amount": 100.00,
            }
        )

        self.backend._create_settlement_entry(group)
        self.assertFalse(group.account_move_id)

    # ── test 8: action_sync_settlements queues job ────────────────────────────

    def test_action_sync_settlements_enqueues_job(self):
        queued = []

        def capturing_with_delay(self_inner, **kw):
            queued.append(kw.get("description", ""))
            mock_job = MagicMock()
            mock_job._pull_settlements = MagicMock()
            return mock_job

        with patch.object(type(self.backend), "with_delay", capturing_with_delay):
            result = self.backend.action_sync_settlements()

        self.assertTrue(queued)
        self.assertIn("settlement", queued[0].lower())
        self.assertEqual(result["type"], "ir.actions.client")
        self.assertEqual(result["tag"], "display_notification")

    # ── Phase 2: tax/shipping/promotion modeling ──────────────────────────────

    def test_settlement_models_tax_shipping_promotion(self):
        """Tax washes to zero; shipping → income CR; promotion → contra DR;
        the unclassified adjustment is ~0 (not the whole tax+shipping gap)."""
        self._configure_backend()
        api = _mock_finances_api(MULTICHARGE_GROUPS_PAYLOAD, MULTICHARGE_EVENTS_PAYLOAD)
        with patch.object(type(self.backend), "_get_api", return_value=api):
            self.backend._pull_settlements()

        group = self.env["amz.settlement.group"].search(
            [("backend_id", "=", self.backend.id), ("amazon_group_id", "=", "GROUPMC")]
        )
        events = group.financial_event_ids
        by_type = {e.event_type: e.amount for e in events}
        # Tax collected (+8) and withheld (−8) net to zero → no tax event emitted.
        self.assertNotIn("tax", by_type, "facilitator tax must wash to zero")
        self.assertAlmostEqual(by_type["shipping"], 5.00, places=2)
        self.assertAlmostEqual(by_type["promotion"], -3.00, places=2)
        self.assertAlmostEqual(by_type["shipment"], 100.00, places=2)

        move = group.account_move_id
        self.assertEqual(move.state, "posted")
        shipping_line = move.line_ids.filtered(
            lambda ln: ln.account_id == self.shipping_account
        )
        self.assertAlmostEqual(shipping_line.credit, 5.00, places=2)
        promo_line = move.line_ids.filtered(
            lambda ln: ln.account_id == self.promotion_account
        )
        self.assertAlmostEqual(promo_line.debit, 3.00, places=2)
        # No tax line (washed) and no meaningful unclassified adjustment.
        self.assertFalse(
            move.line_ids.filtered(lambda ln: ln.account_id == self.tax_account)
        )
        adj = move.line_ids.filtered(lambda ln: "unclassified" in (ln.name or ""))
        self.assertFalse(adj, "fully-modeled settlement needs no adjustment line")

    def test_settlement_parses_refund_with_adjustments(self):
        """RefundEvents reverse principal/charges; refund event is negative."""
        self._configure_backend()
        refund_payload = {
            "FinancialEvents": {
                "ShipmentEvents": [],
                "RefundEvents": [
                    {
                        "AmazonOrderId": "999-888-777",
                        "PostedDate": "2024-05-02T00:00:00Z",
                        "ShipmentItemAdjustmentList": [
                            {
                                "ItemChargeAdjustmentList": [
                                    {
                                        "ChargeType": "Principal",
                                        "ChargeAmount": {"Amount": "20.00"},
                                    }
                                ]
                            }
                        ],
                    }
                ],
                "ServiceFeeEvents": [],
                "AdvertisingFeeEvents": [],
            }
        }
        groups = {
            "FinancialEventGroupList": [
                {**SANDBOX_GROUP_DATA, "FinancialEventGroupId": "GROUPRF"}
            ]
        }
        api = _mock_finances_api(groups, refund_payload)
        with patch.object(type(self.backend), "_get_api", return_value=api):
            self.backend._pull_settlements()

        group = self.env["amz.settlement.group"].search(
            [("backend_id", "=", self.backend.id), ("amazon_group_id", "=", "GROUPRF")]
        )
        refund = group.financial_event_ids.filtered(lambda e: e.event_type == "refund")
        self.assertTrue(refund)
        self.assertAlmostEqual(refund.amount, -20.00, places=2)
        self.assertEqual(group.account_move_id.state, "posted")

    # ── Phase 2: settlement ↔ invoice reconciliation ──────────────────────────

    def _make_order_with_invoice(self, amz_order_id, invoice_untaxed):
        """Create an amz.order + sale.order + posted out_invoice for the given
        untaxed amount, linked so sale_order.invoice_ids resolves it."""
        partner = self.env["res.partner"].create({"name": f"Cust {amz_order_id}"})
        sale = self.env["sale.order"].create({"partner_id": partner.id})
        amz_order = self.env["amz.order"].create(
            {
                "backend_id": self.backend.id,
                "amz_order_id": amz_order_id,
                "sale_order_id": sale.id,
            }
        )
        sale_journal = self.env["account.journal"].search(
            [("type", "=", "sale"), ("company_id", "=", self.env.company.id)],
            limit=1,
        ) or self.env["account.journal"].create(
            {"name": "Amazon Sales Jrnl", "type": "sale", "code": "AMZSJ"}
        )
        line = self.env["sale.order.line"].create(
            {"order_id": sale.id, "name": "x", "price_unit": invoice_untaxed}
        )
        invoice = self.env["account.move"].create(
            {
                "move_type": "out_invoice",
                "partner_id": partner.id,
                "journal_id": sale_journal.id,
                "invoice_line_ids": [
                    (
                        0,
                        0,
                        {
                            "name": "Amazon item",
                            "quantity": 1,
                            "price_unit": invoice_untaxed,
                            "tax_ids": [(6, 0, [])],
                            "account_id": self.income_account.id,
                            "sale_line_ids": [(6, 0, [line.id])],
                        },
                    )
                ],
            }
        )
        invoice.action_post()
        return amz_order, invoice

    def _settlement_for_order(self, group_id, amz_order_id, principal):
        group = self.env["amz.settlement.group"].create(
            {
                "backend_id": self.backend.id,
                "amazon_group_id": group_id,
                "processing_status": "Closed",
                "converted_total": principal,
                "currency_id": self.usd.id,
            }
        )
        self.env["amz.financial.event"].create(
            {
                "settlement_group_id": group.id,
                "event_type": "shipment",
                "amz_order_id": amz_order_id,
                "amount": principal,
            }
        )
        return group

    def test_reconciliation_matched(self):
        self._configure_backend()
        self._make_order_with_invoice("REC-MATCH", 100.00)
        group = self._settlement_for_order("RECG1", "REC-MATCH", 100.00)
        self.backend._reconcile_settlement(group)
        recon = group.reconciliation_ids
        self.assertEqual(len(recon), 1)
        self.assertEqual(recon.state, "matched")
        self.assertAlmostEqual(recon.variance, 0.0, places=2)

    def test_reconciliation_variance(self):
        self._configure_backend()
        self._make_order_with_invoice("REC-VAR", 90.00)
        group = self._settlement_for_order("RECG2", "REC-VAR", 100.00)
        self.backend._reconcile_settlement(group)
        recon = group.reconciliation_ids
        self.assertEqual(recon.state, "variance")
        self.assertAlmostEqual(recon.variance, 10.00, places=2)

    def test_reconciliation_no_invoice(self):
        self._configure_backend()
        self.env["amz.order"].create(
            {"backend_id": self.backend.id, "amz_order_id": "REC-NOINV"}
        )
        group = self._settlement_for_order("RECG3", "REC-NOINV", 100.00)
        self.backend._reconcile_settlement(group)
        recon = group.reconciliation_ids
        self.assertEqual(recon.state, "no_invoice")
