from odoo import fields, models


class AmazonReturn(models.Model):
    _name = "amz.return"
    _description = "Amazon Return"
    _rec_name = "rma_id"
    _order = "return_date desc"

    backend_id = fields.Many2one(
        "amz.backend",
        required=True,
        index=True,
        ondelete="cascade",
    )
    amazon_order_id = fields.Char("Amazon Order ID", index=True)
    order_id = fields.Many2one("amz.order", "Amazon Order", ondelete="set null")
    rma_id = fields.Char("RMA", required=True, index=True)
    return_date = fields.Datetime()
    amazon_status = fields.Char()
    state = fields.Selection(
        [
            ("new", "New"),
            ("picking_created", "Picking Created"),
            ("credited", "Credited"),
            ("done", "Done"),
        ],
        default="new",
        index=True,
    )
    return_picking_id = fields.Many2one(
        "stock.picking", "Return Picking", ondelete="set null"
    )
    credit_note_id = fields.Many2one("account.move", "Credit Note", ondelete="set null")
    refund_event_id = fields.Many2one(
        "amz.financial.event", "Refund Event", ondelete="set null"
    )
    line_ids = fields.One2many("amz.return.line", "return_id", "Lines")
    currency_id = fields.Many2one(
        "res.currency", default=lambda self: self.env.company.currency_id
    )

    _amz_return_rma_uniq = models.Constraint(
        "UNIQUE(backend_id, rma_id)",
        "This Amazon return (RMA) is already imported for this backend.",
    )
