import types

from odoo import fields, models
from odoo.exceptions import UserError

MARKETPLACES = [
    ("ATVPDKIKX0DER", "US — amazon.com"),
    ("A2EUQ1WTGCTBG2", "Canada — amazon.ca"),
    ("A1AM78C64UM0Y8", "Mexico — amazon.com.mx"),
    ("A2Q3Y263D00KWC", "Brazil — amazon.com.br"),
    ("A1RKKUPIHCS9HS", "Spain — amazon.es"),
    ("A1F83G8C2ARO7P", "UK — amazon.co.uk"),
    ("A13V1IB3VIYZZH", "France — amazon.fr"),
    ("A1PA6795UKMFR9", "Germany — amazon.de"),
    ("APJ6JRA9NG5V4", "Italy — amazon.it"),
    ("A2NODRKZP88ZB9", "Netherlands — amazon.nl"),
    ("A1805IZSGTT6HS", "Poland — amazon.pl"),
    ("A2VIGQ35RCS4UG", "UAE — amazon.ae"),
    ("A21TJRUUN4KGV", "India — amazon.in"),
    ("A39IBJ37TRP1C6", "Australia — amazon.com.au"),
    ("A1VC38T7YXB528", "Japan — amazon.co.jp"),
    ("A19VAU5U5O7RUS", "Singapore — amazon.sg"),
]

# NA marketplaces use sellingpartnerapi-na, EU use -eu, FE use -fe
_MARKETPLACE_REGION_SUFFIX = {
    "ATVPDKIKX0DER": "na",
    "A2EUQ1WTGCTBG2": "na",
    "A1AM78C64UM0Y8": "na",
    "A2Q3Y263D00KWC": "na",
    "A1RKKUPIHCS9HS": "eu",
    "A1F83G8C2ARO7P": "eu",
    "A13V1IB3VIYZZH": "eu",
    "A1PA6795UKMFR9": "eu",
    "APJ6JRA9NG5V4": "eu",
    "A2NODRKZP88ZB9": "eu",
    "A1805IZSGTT6HS": "eu",
    "A2VIGQ35RCS4UG": "eu",
    "A21TJRUUN4KGV": "eu",
    "A39IBJ37TRP1C6": "fe",
    "A1VC38T7YXB528": "fe",
    "A19VAU5U5O7RUS": "fe",
}


class AmazonBackend(models.Model):
    _name = "amz.backend"
    _description = "Amazon SP-API Backend"
    _inherit = ["mail.thread"]

    name = fields.Char(required=True)
    active = fields.Boolean(default=True)
    company_id = fields.Many2one(
        "res.company",
        required=True,
        default=lambda self: self.env.company,
    )
    warehouse_id = fields.Many2one(
        "stock.warehouse",
        required=True,
        default=lambda self: self.env["stock.warehouse"].search(
            [("company_id", "=", self.env.company.id)], limit=1
        ),
    )

    # SP-API credentials
    client_id = fields.Char("LWA Client ID", required=True)
    client_secret = fields.Char(
        "LWA Client Secret", required=True, groups="base.group_system"
    )
    refresh_token = fields.Char(
        "LWA Refresh Token", required=True, groups="base.group_system"
    )

    marketplace_id = fields.Selection(
        MARKETPLACES,
        string="Marketplace",
        required=True,
        default="ATVPDKIKX0DER",
    )
    sandbox = fields.Boolean(
        "Sandbox Mode",
        default=False,
        help="Use Amazon SP-API sandbox endpoints. "
        "Requires credentials created in the developer sandbox.",
    )

    import_days_back = fields.Integer(
        "Initial Import Days Back",
        default=7,
        help="On first import, fetch orders updated this many days ago.",
    )
    last_import_date = fields.Datetime(
        "Last Order Import",
        readonly=True,
        help="Cursor for incremental order polling.",
    )

    def _get_credentials(self):
        self.ensure_one()
        return {
            "lwa_app_id": self.client_id,
            "lwa_client_secret": self.client_secret,
            "refresh_token": self.refresh_token,
        }

    def _get_api(self, api_class):
        """Return an SP-API client instance for this backend.

        Builds a synthetic marketplace namespace to avoid mutating the
        module-level AWS_ENV global, which is not thread-safe.
        """
        self.ensure_one()
        from sp_api.base import Marketplaces

        suffix = _MARKETPLACE_REGION_SUFFIX.get(self.marketplace_id, "na")
        base = "sandbox.sellingpartnerapi" if self.sandbox else "sellingpartnerapi"
        endpoint = f"https://{base}-{suffix}.amazon.com"

        # Find the matching Marketplace enum member for region metadata
        sp_marketplace = next(
            (m for m in Marketplaces if m.marketplace_id == self.marketplace_id),
            Marketplaces.US,
        )

        fake_marketplace = types.SimpleNamespace(
            endpoint=endpoint,
            marketplace_id=self.marketplace_id,
            region=sp_marketplace.region,
        )

        return api_class(
            marketplace=fake_marketplace,
            credentials=self._get_credentials(),
        )

    def action_test_connection(self):
        self.ensure_one()
        from sp_api.api import Orders
        from sp_api.base import SellingApiException

        try:
            api = self._get_api(Orders)
            if self.sandbox:
                res = api.get_orders(
                    CreatedAfter="TEST_CASE_200",
                    MarketplaceIds=[self.marketplace_id],
                )
            else:
                import datetime

                since = datetime.datetime.utcnow() - datetime.timedelta(days=1)
                res = api.get_orders(
                    CreatedAfter=since.isoformat() + "Z",
                    MarketplaceIds=[self.marketplace_id],
                )
            order_count = len(res.payload.get("Orders", []))
            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": self.env._("Connection successful"),
                    "message": self.env._(
                        "Retrieved %(count)d order(s) from Amazon.",
                        count=order_count,
                    ),
                    "type": "success",
                },
            }
        except SellingApiException as exc:
            raise UserError(self.env._("Amazon SP-API error: %s", exc)) from exc
        except Exception as exc:
            raise UserError(self.env._("Connection failed: %s", exc)) from exc
