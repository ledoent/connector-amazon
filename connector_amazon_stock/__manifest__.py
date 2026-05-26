{
    "name": "Amazon SP-API Connector: Tracking",
    "version": "19.0.1.0.0",
    "category": "Inventory/Inventory",
    "summary": "Push carrier tracking numbers to Amazon via ConfirmShipment",
    "author": "Ledo, Odoo Community Association (OCA)",
    "website": "https://github.com/OCA/connector-amazon",
    "license": "AGPL-3",
    "depends": [
        "connector_amazon_sale",
        "stock",
        "delivery",
    ],
    "data": [
        "views/stock_picking_views.xml",
    ],
    "maintainers": ["dnplkndll"],
    "development_status": "Alpha",
    "installable": True,
}
