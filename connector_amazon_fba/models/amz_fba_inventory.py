from odoo import api, fields, models


class AmazonFbaInventory(models.Model):
    _name = "amz.fba.inventory"
    _description = "Amazon FBA Inventory"
    _rec_name = "seller_sku"
    _order = "seller_sku"

    backend_id = fields.Many2one(
        "amz.backend",
        required=True,
        index=True,
        ondelete="cascade",
    )
    seller_sku = fields.Char(index=True)
    asin = fields.Char()
    fnsku = fields.Char()
    product_id = fields.Many2one("product.product", "Product")
    fulfillable_qty = fields.Float("Fulfillable")
    inbound_qty = fields.Float("Inbound")
    reserved_qty = fields.Float("Reserved")
    unsellable_qty = fields.Float("Unsellable")
    total_fba_qty = fields.Float("Total FBA")
    odoo_qty = fields.Float("Odoo On-Hand")
    drift = fields.Float(compute="_compute_drift", store=True)
    last_sync_date = fields.Datetime("Last Sync", readonly=True)

    _amz_fba_inventory_uniq = models.Constraint(
        "UNIQUE(backend_id, seller_sku)",
        "FBA inventory already tracked for this SKU on this backend.",
    )

    @api.depends("fulfillable_qty", "odoo_qty")
    def _compute_drift(self):
        for rec in self:
            rec.drift = rec.fulfillable_qty - rec.odoo_qty
