import datetime
import logging

from odoo import fields, models

_logger = logging.getLogger(__name__)

_CANCELLABLE_STATUSES = {"Canceled", "Unfulfillable"}


class AmazonBackend(models.Model):
    _inherit = "amz.backend"

    team_id = fields.Many2one("crm.team", string="Sales Team")
    pricelist_id = fields.Many2one(
        "product.pricelist",
        string="Pricelist",
        help="Applied to imported sale orders. Defaults to company pricelist.",
    )

    def import_orders(self):
        """Poll GetOrders and enqueue one job per order.

        Called by ir.cron or manually. Updates last_import_date on success.
        """
        self.ensure_one()
        from sp_api.api import Orders
        from sp_api.base import SellingApiException

        if self.last_import_date:
            since = self.last_import_date
        else:
            since = datetime.datetime.utcnow() - datetime.timedelta(
                days=self.import_days_back
            )

        api = self._get_api(Orders)
        next_token = None
        imported = 0

        try:
            while True:
                kwargs = {
                    "MarketplaceIds": [self.marketplace_id],
                    "LastUpdatedAfter": since.strftime("%Y-%m-%dT%H:%M:%SZ"),
                }
                if next_token:
                    kwargs["NextToken"] = next_token

                res = api.get_orders(**kwargs)
                payload = res.payload

                for order_data in payload.get("Orders", []):
                    status = order_data.get("OrderStatus", "")
                    if status in _CANCELLABLE_STATUSES:
                        continue
                    self.with_delay(
                        description=f"Import Amazon order {order_data['AmazonOrderId']}"
                    )._import_order(order_data["AmazonOrderId"])
                    imported += 1

                next_token = payload.get("NextToken")
                if not next_token:
                    break

        except SellingApiException as exc:
            _logger.error("Amazon GetOrders failed for backend %s: %s", self.name, exc)
            raise

        self.last_import_date = datetime.datetime.utcnow()
        _logger.info("Backend %s: enqueued %d order import jobs.", self.name, imported)

    def _import_order(self, amazon_order_id):
        """Fetch full order data and create/update amz.order + sale.order."""
        self.ensure_one()
        from sp_api.api import Orders

        api = self._get_api(Orders)

        items_res = api.get_order_items(amazon_order_id)
        address_res = api.get_order_address(amazon_order_id)

        items_payload = items_res.payload
        address_payload = address_res.payload

        amz_order = self.env["amz.order"].search(
            [("backend_id", "=", self.id), ("amz_order_id", "=", amazon_order_id)],
            limit=1,
        )

        shipping_address = address_payload.get("ShippingAddress", {})
        partner = self.env["res.partner"]._find_or_create_amazon_partner(
            shipping_address, amazon_order_id
        )

        order_vals = {
            "backend_id": self.id,
            "amz_order_id": amazon_order_id,
            "amazon_status": items_payload.get("OrderStatus", "Unshipped"),
            "sync_date": datetime.datetime.utcnow(),
        }

        if not amz_order:
            amz_order = self.env["amz.order"].create(order_vals)
        else:
            amz_order.write(order_vals)

        if not amz_order.sale_order_id:
            sale_order = self.env["sale.order"]._create_from_amazon(
                amz_order, partner, items_payload.get("OrderItems", []), self
            )
            amz_order.sale_order_id = sale_order

        amz_order._sync_lines(items_payload.get("OrderItems", []))
