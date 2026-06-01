## Sale-import settings on the backend

This module adds three fields to the Amazon backend
(**Amazon > Configuration > Backends**, *Import Settings* group):

| Field | Notes |
|-------|-------|
| **Sales Team** | `crm.team` set on every imported sale order (optional). |
| **Pricelist** | `product.pricelist` applied to imported orders. Defaults to the company pricelist when left empty. |
| **Auto-Invoice Orders** | Off by default. When on, each imported order is confirmed and a customer invoice is created and posted. Requires invoiceable products — `invoice_policy = 'order'` is recommended; otherwise the step logs "nothing to invoice" and skips. |

## Product master data (required for SKU mapping)

Order lines are matched to Odoo products by **Internal Reference**
(`product.product.default_code`) equal to the Amazon **Seller SKU**. Populate
the internal reference on every product you sell on Amazon. Unmatched SKUs are
imported as description-only sale order lines so no order is dropped.

## Scheduled import

The **Amazon: Import Orders** cron (shipped disabled by the core module) calls
`import_orders()`, which this module provides. Enable it under **Settings >
Technical > Automation > Scheduled Actions** once your backends and product
references are configured.
