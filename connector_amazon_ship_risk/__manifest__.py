{
    "name": "Amazon SP-API Connector: Shipping Risk",
    "version": "19.0.1.1.0",
    "category": "Sales/Sales",
    "summary": "Flag merchant orders at risk of missing the Amazon ship-by cutoff",
    "author": "Ledo, Odoo Community Association (OCA)",
    "website": "https://github.com/OCA/connector-amazon",
    "license": "AGPL-3",
    "depends": [
        "connector_amazon_sale",
        "connector_amazon_stock",
    ],
    "data": [
        "data/ir_cron.xml",
        "views/amz_ship_risk_views.xml",
    ],
    "maintainers": ["dnplkndll"],
    "development_status": "Beta",
    "external_dependencies": {
        "python": ["python-amazon-sp-api"],
    },
    "installable": True,
}
