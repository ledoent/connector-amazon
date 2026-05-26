import logging

from odoo import models

_logger = logging.getLogger(__name__)


class SaleOrder(models.Model):
    _inherit = "sale.order"

    @classmethod
    def _create_from_amazon(cls, amz_order, partner, order_items, backend):
        """Create a sale.order from an amz.order + items list."""
        SaleOrder = cls  # noqa: N806 — using classmethod for clarity
        env = backend.env

        order_vals = {
            "partner_id": partner.id,
            "warehouse_id": backend.warehouse_id.id,
            "company_id": backend.company_id.id,
            "client_order_ref": amz_order.amz_order_id,
            "origin": f"Amazon {amz_order.amz_order_id}",
        }
        if backend.team_id:
            order_vals["team_id"] = backend.team_id.id
        if backend.pricelist_id:
            order_vals["pricelist_id"] = backend.pricelist_id.id

        sale_order = env["sale.order"].create(order_vals)

        for item in order_items:
            sku = item.get("SellerSKU", "")
            product = env["product.product"].search(
                [("default_code", "=", sku)], limit=1
            )
            price_info = item.get("ItemPrice", {})
            unit_price = 0.0
            qty = item.get("QuantityOrdered", 1)
            if qty and float(price_info.get("Amount", 0)):
                unit_price = float(price_info["Amount"]) / qty

            line_vals = {
                "order_id": sale_order.id,
                "name": item.get("Title", sku or "Amazon Product")[:255],
                "product_id": product.id if product else False,
                "product_uom_qty": qty,
                "price_unit": unit_price,
            }
            if not product:
                _logger.warning(
                    "Amazon order %s: no product found for SKU %r — "
                    "line created without product.",
                    amz_order.amz_order_id,
                    sku,
                )
            env["sale.order.line"].create(line_vals)

        return sale_order
