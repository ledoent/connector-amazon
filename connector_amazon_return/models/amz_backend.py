import datetime
import logging
import xml.etree.ElementTree as ET

from odoo import fields, models

_logger = logging.getLogger(__name__)

_RETURNS_REPORT_TYPE = "GET_XML_RETURNS_DATA_BY_RETURN_DATE"

# Element local-names (namespace/case-insensitive) we treat as a return row and
# as an item within a row. The MFN returns report's exact tag names are
# confirmed against a live sample; matching by local-name keeps the parser
# resilient to namespaces and minor schema variation.
_RETURN_ROW_TAGS = {"return", "returndetails", "amazonreturndetails", "row", "record"}
_ITEM_TAGS = {"item", "returnitem", "orderitem", "lineitem"}


def _parse_amz_dt(value):
    """Parse an Amazon ISO 8601 datetime string into a Python datetime."""
    if not value:
        return False
    value = value.strip()
    if value.endswith("Z"):
        value = value[:-1]
    try:
        return datetime.datetime.fromisoformat(value)
    except ValueError:
        return False


def _local(tag):
    """Strip XML namespace and lowercase a tag for resilient matching."""
    return tag.rsplit("}", 1)[-1].lower()


def _ftext(node, *names):
    """First non-empty descendant text whose local-name is in ``names``."""
    wanted = {n.lower() for n in names}
    for child in node.iter():
        if _local(child.tag) in wanted and (child.text or "").strip():
            return child.text.strip()
    return ""


class AmazonBackend(models.Model):
    _inherit = "amz.backend"

    amazon_returns_enabled = fields.Boolean(
        "Sync Returns",
        default=False,
        help="Pull Amazon MFN returns on the returns cron for this backend.",
    )
    amazon_auto_return_picking = fields.Boolean(
        "Auto Restock Returns",
        default=False,
        help="Create a restock receipt (customer → stock) for each return, left "
        "un-validated for the warehouse to confirm on physical receipt.",
    )
    amazon_auto_credit_note = fields.Boolean(
        "Auto Credit Note",
        default=False,
        help="Create and post a credit note for the returned lines, linked to the "
        "original customer invoice and the settlement refund event.",
    )
    last_return_sync_date = fields.Datetime("Last Return Sync", readonly=True)
    amz_return_ids = fields.One2many("amz.return", "backend_id", "Returns")

    # ── actions / cron ────────────────────────────────────────────────────────

    def action_sync_returns(self):
        """Queue a returns pull job for this backend."""
        self.ensure_one()
        self.with_delay(description=f"Sync returns for {self.name}")._pull_returns()
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": "Sync Queued",
                "message": "Returns pull has been queued.",
                "type": "info",
            },
        }

    def sync_returns(self):
        """Cron entry point — enqueue a returns pull per enabled backend."""
        for backend in self.filtered(lambda b: b.active and b.amazon_returns_enabled):
            backend.with_delay(
                description=f"Sync returns for {backend.name}"
            )._pull_returns()

    def _pull_returns(self):
        """Request a fresh returns report and fetch any that are ready."""
        self.ensure_one()
        self._request_returns_report()
        self._fetch_returns_reports()

    # ── Reports API: request ────────────────────────────────────────────────

    def _request_returns_report(self):
        self.ensure_one()
        from sp_api.api import Reports
        from sp_api.base import SellingApiException

        api = self._get_api(Reports)
        end = fields.Datetime.now()
        start = self.last_return_sync_date or (end - datetime.timedelta(days=30))
        # Amazon accepts at most 60 days of returns data per report; clamp a stale
        # cursor so the request isn't rejected.
        floor = end - datetime.timedelta(days=60)
        if start < floor:
            start = floor
        try:
            res = api.create_report(
                reportType=_RETURNS_REPORT_TYPE,
                dataStartTime=start.strftime("%Y-%m-%dT%H:%M:%SZ"),
                dataEndTime=end.strftime("%Y-%m-%dT%H:%M:%SZ"),
                marketplaceIds=[self.marketplace_id],
            )
        except SellingApiException as exc:
            _logger.error(
                "returns report request failed for backend %s: %s", self.name, exc
            )
            return
        report_id = (res.payload or {}).get("reportId")
        if report_id:
            self.env["amz.return.report"].create(
                {
                    "backend_id": self.id,
                    "report_id": report_id,
                    "state": "requested",
                    "data_start": start,
                    "data_end": end,
                }
            )

    # ── Reports API: fetch + parse ───────────────────────────────────────────

    def _fetch_returns_reports(self):
        self.ensure_one()
        from sp_api.api import Reports
        from sp_api.base import SellingApiException

        api = self._get_api(Reports)
        pending = self.env["amz.return.report"].search(
            [("backend_id", "=", self.id), ("state", "=", "requested")]
        )
        parsed_any = False
        for report in pending:
            try:
                status = api.get_report(report.report_id).payload or {}
            except SellingApiException as exc:
                _logger.warning(
                    "get_report failed for %s on backend %s: %s",
                    report.report_id,
                    self.name,
                    exc,
                )
                continue
            proc = status.get("processingStatus")
            if proc in ("CANCELLED", "FATAL"):
                report.state = "error"
                continue
            if proc != "DONE":
                continue  # IN_QUEUE / IN_PROGRESS — retry on the next cron pass
            report.write(
                {"document_id": status.get("reportDocumentId"), "state": "done"}
            )
            try:
                doc = api.get_report_document(report.document_id, decrypt=True)
            except SellingApiException as exc:
                _logger.warning(
                    "get_report_document failed for %s: %s", report.document_id, exc
                )
                report.state = "error"
                continue
            text = self._returns_document_text(doc)
            if not text:
                report.state = "error"
                continue
            self._parse_returns_xml(text)
            report.state = "parsed"
            parsed_any = True
        if parsed_any:
            self.last_return_sync_date = fields.Datetime.now()

    def _returns_document_text(self, doc):
        """Extract the decoded report body from a get_report_document response."""
        payload = getattr(doc, "payload", doc) or {}
        if isinstance(payload, dict):
            return payload.get("document") or ""
        return payload or ""

    def _parse_returns_xml(self, text):
        """Parse an MFN returns report into amz.return(+lines), grouped by RMA."""
        self.ensure_one()
        try:
            root = ET.fromstring(text)
        except ET.ParseError as exc:
            _logger.warning(
                "could not parse returns XML for backend %s: %s", self.name, exc
            )
            return
        rows = [el for el in root.iter() if _local(el.tag) in _RETURN_ROW_TAGS]
        if not rows:
            rows = [root]

        # Group rows by RMA so a flat report (one row per item) and a nested one
        # (one row with item children) both collapse to one return per RMA.
        by_rma = {}
        for row in rows:
            rma = _ftext(row, "returnrequestid", "rmaid", "rma", "returnid")
            if not rma:
                continue
            hdr = by_rma.setdefault(
                rma,
                {
                    "amazon_order_id": _ftext(row, "amazonorderid", "orderid"),
                    "return_date": _parse_amz_dt(
                        _ftext(row, "returndate", "returnrequestdate")
                    ),
                    "amazon_status": _ftext(row, "status", "returnstatus"),
                    "lines": [],
                },
            )
            items = [el for el in row.iter() if _local(el.tag) in _ITEM_TAGS] or [row]
            for item in items:
                hdr["lines"].append(
                    {
                        "order_item_id": _ftext(item, "orderitemid"),
                        "seller_sku": _ftext(item, "merchantsku", "sellersku", "sku"),
                        "asin": _ftext(item, "asin"),
                        "quantity": float(
                            _ftext(item, "quantity", "returnquantity") or 1
                        ),
                        "return_reason": _ftext(item, "returnreason", "reason"),
                    }
                )
        for rma, hdr in by_rma.items():
            self._upsert_return(rma, hdr)

    # ── Upsert + downstream actions ──────────────────────────────────────────

    def _upsert_return(self, rma, hdr):
        existing = self.env["amz.return"].search(
            [("backend_id", "=", self.id), ("rma_id", "=", rma)], limit=1
        )
        if existing:
            # Idempotent on the return itself, but self-heal any enabled downstream
            # artifact that wasn't created yet (e.g. invoice posted after the first
            # ingest, or a transient failure) — mirrors settlement reconciliation.
            self._run_return_automation(existing)
            return existing

        order = self.env["amz.order"].search(
            [
                ("backend_id", "=", self.id),
                ("amz_order_id", "=", hdr.get("amazon_order_id")),
            ],
            limit=1,
        )
        line_vals = []
        for line in hdr["lines"]:
            sku = line.get("seller_sku")
            product = (
                self.env["product.product"].search(
                    [("default_code", "=", sku)], limit=1
                )
                if sku
                else self.env["product.product"]
            )
            order_line = self.env["amz.order.line"]
            if order and sku:
                order_line = order.amz_order_line_ids.filtered(
                    lambda lst, s=sku: lst.seller_sku == s
                )[:1]
            line_vals.append(
                (
                    0,
                    0,
                    {
                        "order_item_id": line.get("order_item_id"),
                        "amz_order_line_id": order_line.id or False,
                        "product_id": product.id or False,
                        "seller_sku": sku,
                        "asin": line.get("asin"),
                        "quantity": line.get("quantity") or 0.0,
                        "return_reason": line.get("return_reason"),
                    },
                )
            )
        amz_return = self.env["amz.return"].create(
            {
                "backend_id": self.id,
                "amazon_order_id": hdr.get("amazon_order_id"),
                "order_id": order.id or False,
                "rma_id": rma,
                "return_date": hdr.get("return_date"),
                "amazon_status": hdr.get("amazon_status"),
                "line_ids": line_vals,
            }
        )
        # Link the settlement refund event for this order, if Phase-2 captured one.
        refund = self.env["amz.financial.event"].search(
            [
                ("event_type", "=", "refund"),
                ("amz_order_id", "=", hdr.get("amazon_order_id")),
            ],
            limit=1,
        )
        if refund:
            amz_return.refund_event_id = refund.id

        self._run_return_automation(amz_return)
        return amz_return

    def _run_return_automation(self, amz_return):
        """Create the enabled, not-yet-created downstream artifacts for a return.

        Best-effort and idempotent: each creator no-ops if its artifact already
        exists, so this is safe to re-run on every ingest (self-heal)."""
        if self.amazon_auto_return_picking and not amz_return.return_picking_id:
            try:
                self._create_return_picking(amz_return)
            except Exception as exc:
                _logger.warning(
                    "return %s: restock picking failed: %s", amz_return.rma_id, exc
                )
        if self.amazon_auto_credit_note and not amz_return.credit_note_id:
            try:
                self._create_credit_note(amz_return)
            except Exception as exc:
                _logger.warning(
                    "return %s: credit note failed: %s", amz_return.rma_id, exc
                )
        amz_return.state = self._return_state(amz_return)

    def _return_state(self, amz_return):
        if amz_return.return_picking_id and amz_return.credit_note_id:
            return "done"
        if amz_return.credit_note_id:
            return "credited"
        if amz_return.return_picking_id:
            return "picking_created"
        return "new"

    def _create_return_picking(self, amz_return):
        """Create an un-validated restock receipt (customer → stock) for the
        returned, stockable products. Phase 1 books a plain incoming receipt; it
        is not chained to the original delivery."""
        warehouse = self.warehouse_id
        pick_type = warehouse.in_type_id
        customer_loc = self.env.ref("stock.stock_location_customers")
        dest_loc = pick_type.default_location_dest_id or warehouse.lot_stock_id
        moves = []
        for line in amz_return.line_ids:
            product = line.product_id
            if not product or product.type == "service" or not line.quantity:
                continue
            moves.append(
                (
                    0,
                    0,
                    {
                        "product_id": product.id,
                        "product_uom_qty": line.quantity,
                        "product_uom": product.uom_id.id,
                        "location_id": customer_loc.id,
                        "location_dest_id": dest_loc.id,
                    },
                )
            )
        if not moves:
            _logger.info(
                "return %s: no stockable lines; no restock picking", amz_return.rma_id
            )
            return
        picking = self.env["stock.picking"].create(
            {
                "picking_type_id": pick_type.id,
                "location_id": customer_loc.id,
                "location_dest_id": dest_loc.id,
                "origin": f"Amazon Return {amz_return.rma_id}",
                "move_ids": moves,
            }
        )
        picking.action_confirm()  # reserve, but leave for the warehouse to validate
        amz_return.return_picking_id = picking.id

    def _create_credit_note(self, amz_return):
        """Post an out_refund for the returned lines, mapped from the original
        invoice (accounts, taxes, unit price) and linked back to it."""
        sale = amz_return.order_id.sale_order_id
        if not sale:
            _logger.info("return %s: no sale order; no credit note", amz_return.rma_id)
            return
        invoice = sale.invoice_ids.filtered(
            lambda m: m.move_type == "out_invoice" and m.state == "posted"
        )[:1]
        if not invoice:
            _logger.info(
                "return %s: no posted invoice; no credit note", amz_return.rma_id
            )
            return
        inv_line_by_product = {
            ln.product_id.id: ln for ln in invoice.invoice_line_ids if ln.product_id
        }
        cn_lines = []
        for line in amz_return.line_ids:
            inv_line = inv_line_by_product.get(line.product_id.id)
            if not inv_line:
                _logger.info(
                    "return %s: product %s not on invoice; line skipped",
                    amz_return.rma_id,
                    line.product_id.display_name or line.seller_sku,
                )
                continue
            cn_lines.append(
                (
                    0,
                    0,
                    {
                        "product_id": line.product_id.id,
                        "quantity": line.quantity,
                        "price_unit": inv_line.price_unit,
                        "tax_ids": [(6, 0, inv_line.tax_ids.ids)],
                        "account_id": inv_line.account_id.id,
                        "name": inv_line.name,
                    },
                )
            )
        if not cn_lines:
            return
        credit_note = self.env["account.move"].create(
            {
                "move_type": "out_refund",
                "partner_id": invoice.partner_id.id,
                "journal_id": invoice.journal_id.id,
                "invoice_origin": f"Amazon Return {amz_return.rma_id}",
                "reversed_entry_id": invoice.id,
                "invoice_line_ids": cn_lines,
            }
        )
        credit_note.action_post()
        amz_return.credit_note_id = credit_note.id
