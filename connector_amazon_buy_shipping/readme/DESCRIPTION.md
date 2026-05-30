This module buys **Amazon shipping labels** for merchant-fulfilled (MFN) orders
directly from Odoo, via the SP-API Merchant Fulfillment service — closing the
loop opened by `connector_amazon_ship_risk`: an order flagged at risk can be
shipped without leaving Odoo.

From a delivery, **Buy Amazon Shipping** fetches the eligible carriers/services
and their rates, you pick one, and Odoo purchases the label: the tracking
number lands on the picking, the label PDF is stored as an attachment, and an
`amz.shipment` record captures the carrier, service and cost.

Because Merchant Fulfillment already confirms the shipment to Amazon when the
label is bought, these deliveries skip the separate ConfirmShipment push so the
order is never double-confirmed.
