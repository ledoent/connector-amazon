from odoo import fields, models


class AmazonListing(models.Model):
    _inherit = "amz.listing"

    last_pushed_qty = fields.Integer(
        default=-1,
        help="Quantity last sent to Amazon. -1 means never pushed.",
    )
    last_inventory_push_date = fields.Datetime("Last Inventory Push", readonly=True)
    inventory_sync_enabled = fields.Boolean(
        "Sync Inventory",
        default=True,
        help="Uncheck to exclude this listing from inventory sync.",
    )
