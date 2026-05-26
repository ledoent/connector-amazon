from odoo import models


class AmazonOrder(models.Model):
    _inherit = "amz.order"

    def _sync_lines(self, order_items):
        """Create or update amz.order.line records from GetOrderItems payload."""
        existing = {ln.order_item_id: ln for ln in self.amz_order_line_ids}

        for item in order_items:
            item_id = item.get("OrderItemId", "")
            price_info = item.get("ItemPrice", {})
            tax_info = item.get("ItemTax", {})
            vals = {
                "amz_order_id": self.id,
                "order_item_id": item_id,
                "asin": item.get("ASIN", ""),
                "seller_sku": item.get("SellerSKU", ""),
                "title": item.get("Title", "")[:255],
                "quantity_ordered": item.get("QuantityOrdered", 0),
                "quantity_shipped": item.get("QuantityShipped", 0),
                "item_price": float(price_info.get("Amount", 0)),
                "item_tax": float(tax_info.get("Amount", 0)),
            }
            if item_id in existing:
                existing[item_id].write(vals)
            else:
                self.env["amz.order.line"].create(vals)
