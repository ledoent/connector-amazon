from unittest.mock import MagicMock, patch

from odoo.tests.common import TransactionCase
from odoo.tools import mute_logger

from odoo.addons.connector_amazon.tests.common import (
    SANDBOX_GET_ORDER_ADDRESS_PAYLOAD,
    SANDBOX_GET_ORDER_ITEMS_PAYLOAD,
)

# The imported order: 1 unit @ 10.00 (Principal), order 902-1845936-5435065.
ORDER_ID = "902-1845936-5435065"
SKU = "NABetaASINB00551Q3CS"

# Settlement for the same order: Principal 10.00, Commission -1.50 → net 8.50.
SETTLEMENT_GROUPS = {
    "FinancialEventGroupList": [
        {
            "FinancialEventGroupId": "E2EGROUP",
            "ProcessingStatus": "Closed",
            "OriginalTotal": {"CurrencyCode": "USD", "Amount": "8.50"},
            "ConvertedTotal": {"CurrencyCode": "USD", "Amount": "8.50"},
            "FundTransferDate": "2024-05-01T00:00:00Z",
        }
    ]
}
SETTLEMENT_EVENTS = {
    "FinancialEvents": {
        "ShipmentEvents": [
            {
                "AmazonOrderId": ORDER_ID,
                "PostedDate": "2024-05-01T00:00:00Z",
                "ShipmentItemList": [
                    {
                        "ItemChargeList": [
                            {
                                "ChargeType": "Principal",
                                "ChargeAmount": {"Amount": "10.00"},
                            }
                        ],
                        "ItemFeeList": [
                            {"FeeType": "Commission", "FeeAmount": {"Amount": "-1.50"}}
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


class TestGoldenPath(TransactionCase):
    """End-to-end chain across both connectors with one consistent dataset:
    import order → confirm → auto-invoice → settlement pull → reconciliation,
    asserting the invoice, the journal entry, and the reconciliation all agree.

    SP-API is mocked, but — unlike the per-method unit tests — a single coherent
    order flows through every stage, so cross-module integration drift is caught.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.backend = cls.env["amz.backend"].create(
            {
                "name": "E2E Backend",
                "client_id": "cid",
                "client_secret": "csec",
                "refresh_token": "rtok",
                "marketplace_id": "ATVPDKIKX0DER",
                "sandbox": True,
                "warehouse_id": cls.env["stock.warehouse"].search([], limit=1).id,
            }
        )
        cls.income = cls.env["account.account"].create(
            {"name": "Amz Income", "code": "E2EINC", "account_type": "income"}
        )
        cls.fee = cls.env["account.account"].create(
            {"name": "Amz Fee", "code": "E2EFEE", "account_type": "expense"}
        )
        cls.bank_journal = cls.env["account.journal"].create(
            {"name": "Amz Bank", "type": "bank", "code": "E2EB"}
        )
        if not cls.env["account.journal"].search(
            [("type", "=", "sale"), ("company_id", "=", cls.env.company.id)], limit=1
        ):
            cls.env["account.journal"].create(
                {"name": "Sales", "type": "sale", "code": "E2ESJ"}
            )
        cls.product = cls.env["product.product"].create(
            {
                "name": "Card Book",
                "default_code": SKU,
                "invoice_policy": "order",
                "list_price": 10.0,
            }
        )
        cls.product.property_account_income_id = cls.income
        cls.backend.write(
            {
                "amazon_auto_invoice": True,
                "amazon_settlement_journal_id": cls.bank_journal.id,
                "amazon_income_account_id": cls.income.id,
                "amazon_fee_account_id": cls.fee.id,
            }
        )

    def _dispatch_api(self):
        """Return a _get_api replacement that serves the right mock per API."""
        orders = MagicMock()
        orders.get_order_items.return_value = MagicMock(
            payload=SANDBOX_GET_ORDER_ITEMS_PAYLOAD
        )
        orders.get_order_address.return_value = MagicMock(
            payload=SANDBOX_GET_ORDER_ADDRESS_PAYLOAD
        )
        finances = MagicMock()
        finances.list_financial_event_groups.return_value = MagicMock(
            payload=SETTLEMENT_GROUPS, next_token=None
        )
        finances.list_financial_events_by_group_id.return_value = MagicMock(
            payload=SETTLEMENT_EVENTS, next_token=None
        )

        def _get_api(self_backend, api_class, *a, **kw):
            return {"Orders": orders, "Finances": finances}.get(
                api_class.__name__, MagicMock()
            )

        return _get_api

    @mute_logger(
        "odoo.addons.connector_amazon_sale.models.sale_order",
        "odoo.addons.connector_amazon_sale.models.amz_backend",
    )
    def test_order_to_settlement_reconciliation(self):
        with patch.object(type(self.backend), "_get_api", self._dispatch_api()):
            # 1. Import the order → sale.order + auto-posted invoice.
            self.backend._import_order(ORDER_ID)

            amz_order = self.env["amz.order"].search(
                [("backend_id", "=", self.backend.id), ("amz_order_id", "=", ORDER_ID)]
            )
            self.assertTrue(amz_order.sale_order_id)
            invoice = amz_order.sale_order_id.invoice_ids.filtered(
                lambda m: m.move_type == "out_invoice"
            )
            self.assertEqual(invoice.state, "posted", "auto-invoice must be posted")
            self.assertAlmostEqual(invoice.amount_untaxed, 10.00, places=2)

            # 2. Pull the settlement for the same order → journal entry + recon.
            self.backend._pull_settlements()

        group = self.env["amz.settlement.group"].search(
            [("backend_id", "=", self.backend.id), ("amazon_group_id", "=", "E2EGROUP")]
        )
        # Journal entry posted and balanced.
        move = group.account_move_id
        self.assertEqual(move.state, "posted")
        self.assertAlmostEqual(
            sum(move.line_ids.mapped("debit")),
            sum(move.line_ids.mapped("credit")),
            places=2,
        )

        # 3. Reconciliation ties the settled Principal to the posted invoice.
        recon = group.reconciliation_ids
        self.assertEqual(len(recon), 1)
        self.assertEqual(recon.amz_order_id, ORDER_ID)
        self.assertEqual(recon.state, "matched")
        self.assertAlmostEqual(recon.settled_principal, 10.00, places=2)
        self.assertAlmostEqual(recon.invoiced_total, 10.00, places=2)
        self.assertAlmostEqual(recon.variance, 0.00, places=2)
        self.assertEqual(recon.invoice_id, invoice)
