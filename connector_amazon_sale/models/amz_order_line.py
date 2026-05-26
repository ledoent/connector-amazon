from odoo import models


class AmazonOrderLine(models.Model):
    _inherit = "amz.order.line"
