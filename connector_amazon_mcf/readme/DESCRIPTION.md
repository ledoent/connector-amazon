This module fulfills **non-Amazon orders out of your FBA stock** using Amazon's
Multi-Channel Fulfillment (Fulfillment Outbound API) — letting Amazon act as a
3PL for your other sales channels.

From any outgoing delivery, **Fulfill via Amazon** builds a fulfillment order:
each product is matched to its FBA seller SKU (via `amz.fba.inventory`), the
delivery address becomes the destination, and on submit Amazon ships from FBA
stock. A scheduled poll (and a manual **Check Status**) tracks the order through
Amazon's lifecycle and writes the returned carrier tracking number back onto the
Odoo delivery.
