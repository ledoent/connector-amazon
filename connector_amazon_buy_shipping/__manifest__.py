{
    "name": "Amazon SP-API Connector: Buy Shipping",
    "version": "19.0.1.1.0",
    "category": "Sales/Sales",
    "summary": "Buy Amazon shipping labels for MFN orders via Merchant Fulfillment",
    "author": "Ledo, Odoo Community Association (OCA)",
    "website": "https://github.com/OCA/connector-amazon",
    "license": "AGPL-3",
    "depends": [
        "connector_amazon_sale",
        "connector_amazon_stock",
    ],
    "data": [
        "security/ir.model.access.csv",
        "wizards/amz_buy_shipping_wizard_views.xml",
        "views/amz_shipment_views.xml",
        "views/stock_picking_views.xml",
        "views/amz_backend_views.xml",
    ],
    "maintainers": ["dnplkndll"],
    "development_status": "Beta",
    "external_dependencies": {
        "python": ["python-amazon-sp-api"],
    },
    "installable": True,
}
