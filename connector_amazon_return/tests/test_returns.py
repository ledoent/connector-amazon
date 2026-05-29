from unittest.mock import MagicMock, patch

from odoo.tests.common import TransactionCase
from odoo.tools import mute_logger

ORDER_ID = "902-1845936-5435065"
SKU = "NABetaASINB00551Q3CS"
LOGGER = "odoo.addons.connector_amazon_return.models.amz_backend"

RETURNS_XML = f"""<?xml version="1.0"?>
<MfnReturnReport>
  <Return>
    <AmazonOrderId>{ORDER_ID}</AmazonOrderId>
    <ReturnRequestId>RMA-001</ReturnRequestId>
    <ReturnDate>2024-05-10T00:00:00Z</ReturnDate>
    <Status>Approved</Status>
    <Item>
      <OrderItemId>05015851154158</OrderItemId>
      <MerchantSKU>{SKU}</MerchantSKU>
      <ASIN>B00551Q3CS</ASIN>
      <Quantity>1</Quantity>
      <ReturnReason>DEFECTIVE</ReturnReason>
    </Item>
  </Return>
</MfnReturnReport>"""


class TestReturns(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.warehouse = cls.env["stock.warehouse"].search([], limit=1)
        cls.backend = cls.env["amz.backend"].create(
            {
                "name": "Return Backend",
                "client_id": "cid",
                "client_secret": "csec",
                "refresh_token": "rtok",
                "marketplace_id": "ATVPDKIKX0DER",
                "sandbox": True,
                "warehouse_id": cls.warehouse.id,
            }
        )
        cls.product = cls.env["product.product"].create(
            {
                "name": "Card Book",
                "default_code": SKU,
                "type": "consu",
                "is_storable": True,
                "list_price": 10.0,
            }
        )
        cls.partner = cls.env["res.partner"].create({"name": "Return Cust"})
        cls.sale = cls.env["sale.order"].create({"partner_id": cls.partner.id})
        cls.amz_order = cls.env["amz.order"].create(
            {
                "backend_id": cls.backend.id,
                "amz_order_id": ORDER_ID,
                "sale_order_id": cls.sale.id,
            }
        )
        cls.env["amz.order.line"].create(
            {
                "amz_order_id": cls.amz_order.id,
                "order_item_id": "05015851154158",
                "seller_sku": SKU,
                "asin": "B00551Q3CS",
                "quantity_ordered": 1,
            }
        )

    # ── helpers ───────────────────────────────────────────────────────────────

    def _mock_reports_api(self, xml_text):
        api = MagicMock()
        api.create_report.return_value = MagicMock(payload={"reportId": "RPT1"})
        api.get_report.return_value = MagicMock(
            payload={"processingStatus": "DONE", "reportDocumentId": "DOC1"}
        )
        api.get_report_document.return_value = MagicMock(payload={"document": xml_text})
        return api

    def _post_invoice(self, untaxed):
        income = self.env["account.account"].create(
            {"name": "Amz Income", "code": "RTINC", "account_type": "income"}
        )
        sale_journal = self.env["account.journal"].search(
            [("type", "=", "sale"), ("company_id", "=", self.env.company.id)], limit=1
        ) or self.env["account.journal"].create(
            {"name": "Sales", "type": "sale", "code": "RTSJ"}
        )
        line = self.env["sale.order.line"].create(
            {"order_id": self.sale.id, "name": "x", "product_id": self.product.id}
        )
        invoice = self.env["account.move"].create(
            {
                "move_type": "out_invoice",
                "partner_id": self.partner.id,
                "journal_id": sale_journal.id,
                "invoice_line_ids": [
                    (
                        0,
                        0,
                        {
                            "product_id": self.product.id,
                            "name": "Card Book",
                            "quantity": 1,
                            "price_unit": untaxed,
                            "tax_ids": [(6, 0, [])],
                            "account_id": income.id,
                            "sale_line_ids": [(6, 0, [line.id])],
                        },
                    )
                ],
            }
        )
        invoice.action_post()
        return invoice

    # ── parsing ─────────────────────────────────────────────────────────────

    def test_parse_creates_return_and_lines(self):
        self.backend._parse_returns_xml(RETURNS_XML)
        ret = self.env["amz.return"].search(
            [("backend_id", "=", self.backend.id), ("rma_id", "=", "RMA-001")]
        )
        self.assertEqual(len(ret), 1)
        self.assertEqual(ret.amazon_order_id, ORDER_ID)
        self.assertEqual(ret.order_id, self.amz_order)
        self.assertEqual(len(ret.line_ids), 1)
        line = ret.line_ids
        self.assertEqual(line.seller_sku, SKU)
        self.assertEqual(line.asin, "B00551Q3CS")
        self.assertEqual(line.product_id, self.product)
        self.assertEqual(line.return_reason, "DEFECTIVE")
        self.assertAlmostEqual(line.quantity, 1.0)

    def test_parse_is_idempotent(self):
        self.backend._parse_returns_xml(RETURNS_XML)
        self.backend._parse_returns_xml(RETURNS_XML)
        ret = self.env["amz.return"].search(
            [("backend_id", "=", self.backend.id), ("rma_id", "=", "RMA-001")]
        )
        self.assertEqual(len(ret), 1, "re-parsing the same RMA must not duplicate")

    def test_refund_event_linked(self):
        # A settlement refund event (Phase 2) for the same order gets linked.
        group = self.env["amz.settlement.group"].create(
            {"backend_id": self.backend.id, "amazon_group_id": "G1"}
        )
        refund = self.env["amz.financial.event"].create(
            {
                "settlement_group_id": group.id,
                "event_type": "refund",
                "amz_order_id": ORDER_ID,
                "amount": -10.0,
            }
        )
        self.backend._parse_returns_xml(RETURNS_XML)
        ret = self.env["amz.return"].search([("rma_id", "=", "RMA-001")])
        self.assertEqual(ret.refund_event_id, refund)

    # ── async report flow ─────────────────────────────────────────────────────

    def test_pull_returns_async_flow(self):
        api = self._mock_reports_api(RETURNS_XML)
        with patch.object(type(self.backend), "_get_api", return_value=api):
            self.backend._pull_returns()

        ret = self.env["amz.return"].search([("rma_id", "=", "RMA-001")])
        self.assertTrue(ret)
        report = self.env["amz.return.report"].search(
            [("backend_id", "=", self.backend.id)]
        )
        self.assertEqual(report.state, "parsed")
        self.backend.invalidate_recordset()
        self.assertTrue(self.backend.last_return_sync_date)

    def test_pull_returns_in_progress_waits(self):
        api = self._mock_reports_api(RETURNS_XML)
        api.get_report.return_value = MagicMock(
            payload={"processingStatus": "IN_PROGRESS"}
        )
        with patch.object(type(self.backend), "_get_api", return_value=api):
            self.backend._pull_returns()
        # No document fetched, report still 'requested', nothing parsed.
        api.get_report_document.assert_not_called()
        report = self.env["amz.return.report"].search(
            [("backend_id", "=", self.backend.id)]
        )
        self.assertEqual(report.state, "requested")
        self.assertFalse(self.env["amz.return"].search([("rma_id", "=", "RMA-001")]))

    # ── auto restock picking ───────────────────────────────────────────────────

    def test_auto_return_picking(self):
        self.backend.amazon_auto_return_picking = True
        self.backend._parse_returns_xml(RETURNS_XML)
        ret = self.env["amz.return"].search([("rma_id", "=", "RMA-001")])
        picking = ret.return_picking_id
        self.assertTrue(picking, "a restock picking must be created")
        self.assertEqual(picking.picking_type_id.code, "incoming")
        self.assertNotEqual(picking.state, "done", "must be left for the warehouse")
        self.assertEqual(picking.move_ids.product_id, self.product)
        self.assertAlmostEqual(picking.move_ids.product_uom_qty, 1.0)
        self.assertIn(ret.state, ("picking_created", "done"))

    def test_no_picking_when_toggle_off(self):
        self.assertFalse(self.backend.amazon_auto_return_picking)
        self.backend._parse_returns_xml(RETURNS_XML)
        ret = self.env["amz.return"].search([("rma_id", "=", "RMA-001")])
        self.assertFalse(ret.return_picking_id)
        self.assertEqual(ret.state, "new")

    # ── auto credit note ───────────────────────────────────────────────────────

    def test_auto_credit_note(self):
        self._post_invoice(10.00)
        self.backend.amazon_auto_credit_note = True
        with mute_logger(LOGGER):
            self.backend._parse_returns_xml(RETURNS_XML)
        ret = self.env["amz.return"].search([("rma_id", "=", "RMA-001")])
        cn = ret.credit_note_id
        self.assertTrue(cn, "a credit note must be created")
        self.assertEqual(cn.move_type, "out_refund")
        self.assertEqual(cn.state, "posted")
        self.assertAlmostEqual(cn.amount_untaxed, 10.00, places=2)
        self.assertEqual(cn.line_ids.mapped("product_id"), self.product)
        self.assertIn(ret.state, ("credited", "done"))

    def test_credit_note_skipped_without_invoice(self):
        self.backend.amazon_auto_credit_note = True
        with mute_logger(LOGGER):
            self.backend._parse_returns_xml(RETURNS_XML)
        ret = self.env["amz.return"].search([("rma_id", "=", "RMA-001")])
        self.assertFalse(ret.credit_note_id, "no invoice → no credit note")
        self.assertEqual(ret.state, "new")

    # ── golden path: picking + credit note + refund link together ──────────────

    def test_golden_path_full_return(self):
        self._post_invoice(10.00)
        group = self.env["amz.settlement.group"].create(
            {"backend_id": self.backend.id, "amazon_group_id": "G9"}
        )
        self.env["amz.financial.event"].create(
            {
                "settlement_group_id": group.id,
                "event_type": "refund",
                "amz_order_id": ORDER_ID,
                "amount": -10.0,
            }
        )
        self.backend.write(
            {"amazon_auto_return_picking": True, "amazon_auto_credit_note": True}
        )
        with mute_logger(LOGGER):
            self.backend._parse_returns_xml(RETURNS_XML)
        ret = self.env["amz.return"].search([("rma_id", "=", "RMA-001")])
        self.assertTrue(ret.return_picking_id)
        self.assertTrue(ret.credit_note_id)
        self.assertTrue(ret.refund_event_id)
        self.assertEqual(ret.state, "done")

    def test_pull_returns_full_automation_e2e(self):
        """The whole return process through the real async entry point:
        _pull_returns (Reports create→fetch→parse) with both toggles ON and a
        posted invoice + refund event present → return ingested AND restocked AND
        credited AND refund-linked, report marked parsed, cursor advanced."""
        self._post_invoice(10.00)
        group = self.env["amz.settlement.group"].create(
            {"backend_id": self.backend.id, "amazon_group_id": "GE2E"}
        )
        self.env["amz.financial.event"].create(
            {
                "settlement_group_id": group.id,
                "event_type": "refund",
                "amz_order_id": ORDER_ID,
                "amount": -10.0,
            }
        )
        self.backend.write(
            {"amazon_auto_return_picking": True, "amazon_auto_credit_note": True}
        )
        api = self._mock_reports_api(RETURNS_XML)
        with (
            patch.object(type(self.backend), "_get_api", return_value=api),
            mute_logger(LOGGER),
        ):
            self.backend._pull_returns()

        ret = self.env["amz.return"].search([("rma_id", "=", "RMA-001")])
        self.assertTrue(ret, "return ingested via _pull_returns")
        self.assertTrue(ret.return_picking_id, "restocked")
        self.assertEqual(ret.credit_note_id.state, "posted", "credited")
        self.assertTrue(ret.refund_event_id, "refund linked")
        self.assertEqual(ret.state, "done")
        report = self.env["amz.return.report"].search(
            [("backend_id", "=", self.backend.id)]
        )
        self.assertEqual(report.state, "parsed")
        self.backend.invalidate_recordset()
        self.assertTrue(self.backend.last_return_sync_date)

    def test_reingest_self_heals_missing_credit_note(self):
        """A return first ingested without an invoice gets its credit note on a
        later ingest once the invoice exists — no duplicate return."""
        self.backend.amazon_auto_credit_note = True
        with mute_logger(LOGGER):
            self.backend._parse_returns_xml(RETURNS_XML)
        ret = self.env["amz.return"].search([("rma_id", "=", "RMA-001")])
        self.assertFalse(ret.credit_note_id)
        self.assertEqual(ret.state, "new")

        self._post_invoice(10.00)
        with mute_logger(LOGGER):
            self.backend._parse_returns_xml(RETURNS_XML)  # re-ingest same RMA
        ret = self.env["amz.return"].search([("rma_id", "=", "RMA-001")])
        self.assertEqual(len(ret), 1, "no duplicate return on re-ingest")
        self.assertTrue(ret.credit_note_id, "credit note self-healed")
        self.assertEqual(ret.state, "credited")

    def test_report_fatal_sets_error(self):
        """A FATAL/CANCELLED report is marked error and parses nothing."""
        api = self._mock_reports_api(RETURNS_XML)
        api.get_report.return_value = MagicMock(payload={"processingStatus": "FATAL"})
        with patch.object(type(self.backend), "_get_api", return_value=api):
            self.backend._pull_returns()
        report = self.env["amz.return.report"].search(
            [("backend_id", "=", self.backend.id)]
        )
        self.assertEqual(report.state, "error")
        api.get_report_document.assert_not_called()
        self.assertFalse(self.env["amz.return"].search([("rma_id", "=", "RMA-001")]))
