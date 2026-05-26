from odoo.tests.common import TransactionCase

from odoo.addons.connector_amazon.tests.common import SANDBOX_GET_ORDER_ADDRESS_PAYLOAD


class TestFindOrCreatePartner(TransactionCase):
    def setUp(self):
        super().setUp()
        self.address = SANDBOX_GET_ORDER_ADDRESS_PAYLOAD["ShippingAddress"]

    def test_creates_partner_from_address(self):
        partner = self.env["res.partner"]._find_or_create_amazon_partner(
            self.address, "902-1845936-5435065"
        )
        self.assertEqual(partner.name, "MFNIntegrationTestMerchant")
        self.assertEqual(partner.city, "SEATTLE")
        self.assertEqual(partner.zip, "98121-2778")
        self.assertEqual(partner.country_id.code, "US")
        self.assertEqual(partner.customer_rank, 1)

    def test_returns_existing_partner(self):
        partner1 = self.env["res.partner"]._find_or_create_amazon_partner(
            self.address, "902-1845936-5435065"
        )
        partner2 = self.env["res.partner"]._find_or_create_amazon_partner(
            self.address, "902-1845936-5435065"
        )
        self.assertEqual(partner1.id, partner2.id, "Must not create duplicate partners")

    def test_fallback_name_when_address_missing_name(self):
        address = dict(self.address)
        del address["Name"]
        partner = self.env["res.partner"]._find_or_create_amazon_partner(
            address, "902-TEST-0001"
        )
        self.assertIn("902-TEST-0001", partner.name)
