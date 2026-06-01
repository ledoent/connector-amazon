{
    "name": "Amazon SP-API Connector: Orders",
    "version": "19.0.1.1.0",
    "category": "Sales/Sales",
    "summary": "Import Amazon orders into Odoo sale.order",
    "author": "Ledo, Odoo Community Association (OCA)",
    "website": "https://github.com/OCA/connector-amazon",
    "license": "AGPL-3",
    "depends": [
        "connector_amazon",
        "sale_management",
        "sale_stock",
        "account",
    ],
    "data": [
        "views/amz_backend_views.xml",
    ],
    "maintainers": ["dnplkndll"],
    "development_status": "Beta",
    "installable": True,
}
