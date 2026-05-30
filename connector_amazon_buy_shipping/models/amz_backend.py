import logging

from odoo import fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class AmzBackend(models.Model):
    _inherit = "amz.backend"

    default_package_weight = fields.Float(default=16.0)
    weight_unit = fields.Selection([("oz", "Ounces"), ("g", "Grams")], default="oz")
    default_package_length = fields.Float("Default Length", default=10.0)
    default_package_width = fields.Float("Default Width", default=8.0)
    default_package_height = fields.Float("Default Height", default=4.0)
    dimension_unit = fields.Selection(
        [("inches", "Inches"), ("centimeters", "Centimeters")], default="inches"
    )
    label_format = fields.Selection(
        [("PNG", "PNG"), ("PDF", "PDF"), ("ZPL203", "ZPL")],
        default="PNG",
    )

    # ── Merchant Fulfillment ───────────────────────────────────────────────────

    @staticmethod
    def _amz_address(partner, company):
        return {
            "Name": (partner.name or company.name or "")[:50],
            "AddressLine1": partner.street or "",
            "AddressLine2": partner.street2 or "",
            "City": partner.city or "",
            "StateOrProvinceCode": partner.state_id.code or "",
            "PostalCode": partner.zip or "",
            "CountryCode": partner.country_id.code or "US",
            "Email": partner.email or "",
            "Phone": partner.phone or "",
        }

    def _amz_shipment_request(self, picking, weight, length, width, height):
        """Build the SP-API ShipmentRequestDetails for a delivery picking."""
        self.ensure_one()
        order = self.env["amz.order"].search(
            [("sale_order_id", "=", picking.sale_id.id), ("backend_id", "=", self.id)],
            limit=1,
        )
        items = [
            {"OrderItemId": ln.order_item_id, "Quantity": ln.quantity_ordered}
            for ln in order.amz_order_line_ids
        ]
        ship_from = self.warehouse_id.partner_id or self.env.company.partner_id
        details = {
            "AmazonOrderId": order.amz_order_id,
            "ItemList": items,
            "ShipFromAddress": self._amz_address(ship_from, self.env.company),
            "PackageDimensions": {
                "Length": length,
                "Width": width,
                "Height": height,
                "Unit": self.dimension_unit,
            },
            "Weight": {"Value": weight, "Unit": self.weight_unit},
            "ShippingServiceOptions": {
                "DeliveryExperience": "DeliveryConfirmationWithoutSignature",
                "CarrierWillPickUp": False,
                "LabelFormat": self.label_format,
            },
        }
        return details, order

    @staticmethod
    def _amz_parse_rate(service):
        rate = service.get("Rate") or {}
        return {
            "shipping_service_id": service.get("ShippingServiceId"),
            "shipping_service_offer_id": service.get("ShippingServiceOfferId"),
            "carrier_name": service.get("CarrierName"),
            "service_name": service.get("ShippingServiceName"),
            "cost": float(rate.get("Amount") or 0.0),
            "currency_name": rate.get("CurrencyCode") or "USD",
            "delivery_date": service.get("EarliestEstimatedDeliveryDate") or "",
        }

    def _amz_get_shipping_rates(self, picking, weight, length, width, height):
        self.ensure_one()
        from sp_api.api import MerchantFulfillment
        from sp_api.base import SellingApiException

        details, _order = self._amz_shipment_request(
            picking, weight, length, width, height
        )
        api = self._get_api(MerchantFulfillment)
        try:
            res = api.get_eligible_shipment_services(details)
        except SellingApiException as exc:
            raise UserError(
                self.env._("Amazon could not return shipping rates: %s", exc)
            ) from exc
        services = (res.payload or {}).get("ShippingServiceList", [])
        return [self._amz_parse_rate(s) for s in services]

    def _amz_purchase_label(
        self, picking, weight, length, width, height, service_id, offer_id
    ):
        self.ensure_one()
        from sp_api.api import MerchantFulfillment
        from sp_api.base import SellingApiException

        details, order = self._amz_shipment_request(
            picking, weight, length, width, height
        )
        api = self._get_api(MerchantFulfillment)
        try:
            res = api.create_shipment(
                details,
                service_id,
                ShippingServiceOfferId=offer_id,
            )
        except SellingApiException as exc:
            raise UserError(
                self.env._("Amazon could not buy the shipping label: %s", exc)
            ) from exc
        payload = res.payload or {}
        service = payload.get("ShippingService") or {}
        rate = service.get("Rate") or {}
        label = (payload.get("Label") or {}).get("FileContents") or {}
        return {
            "amazon_shipment_id": payload.get("ShipmentId"),
            "tracking_number": payload.get("TrackingId"),
            "carrier_name": service.get("CarrierName"),
            "service_name": service.get("ShippingServiceName"),
            "cost": float(rate.get("Amount") or 0.0),
            "currency_name": rate.get("CurrencyCode") or "USD",
            "label_contents": label.get("Contents"),
            "label_type": label.get("FileType") or "PDF",
            "order_id": order.id if order else False,
        }
