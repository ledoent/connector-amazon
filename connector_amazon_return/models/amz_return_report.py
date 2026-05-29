from odoo import fields, models


class AmazonReturnReport(models.Model):
    _name = "amz.return.report"
    _description = "Amazon Returns Report Request"
    _order = "create_date desc"

    backend_id = fields.Many2one(
        "amz.backend",
        required=True,
        index=True,
        ondelete="cascade",
    )
    report_id = fields.Char("Report ID", index=True)
    document_id = fields.Char("Report Document ID")
    state = fields.Selection(
        [
            ("requested", "Requested"),
            ("done", "Done"),
            ("parsed", "Parsed"),
            ("error", "Error"),
        ],
        default="requested",
        index=True,
    )
    data_start = fields.Datetime()
    data_end = fields.Datetime()
