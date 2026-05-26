from odoo import models


class ResPartner(models.Model):
    _inherit = "res.partner"

    def _find_or_create_amazon_partner(self, shipping_address, amazon_order_id):
        """Return or create a partner from an Amazon shipping address dict."""
        name = shipping_address.get("Name") or f"Amazon Order {amazon_order_id}"
        country_code = shipping_address.get("CountryCode", "US")
        state_code = shipping_address.get("StateOrRegion", "")
        postal_code = shipping_address.get("PostalCode", "")
        city = shipping_address.get("City", "")
        address_line1 = shipping_address.get("AddressLine1", "")
        address_line2 = shipping_address.get("AddressLine2", "")
        phone = shipping_address.get("Phone", "")

        country = self.env["res.country"].search([("code", "=", country_code)], limit=1)
        state = (
            self.env["res.country.state"].search(
                [("code", "=", state_code), ("country_id", "=", country.id)], limit=1
            )
            if state_code
            else self.env["res.country.state"]
        )

        domain = [
            ("name", "=", name),
            ("zip", "=", postal_code),
            ("country_id", "=", country.id),
        ]
        partner = self.search(domain, limit=1)
        if partner:
            return partner

        return self.create(
            {
                "name": name,
                "street": address_line1,
                "street2": address_line2,
                "city": city,
                "zip": postal_code,
                "state_id": state.id if state else False,
                "country_id": country.id if country else False,
                "phone": phone,
                "customer_rank": 1,
            }
        )
