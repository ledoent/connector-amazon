from unittest.mock import MagicMock, patch

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

    def _configure_backend(self):
        self.backend.write(
            {
                "amazon_settlement_journal_id": self.bank_journal.id,
                "amazon_income_account_id": self.income_account.id,
                "amazon_fee_account_id": self.fee_account.id,
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
