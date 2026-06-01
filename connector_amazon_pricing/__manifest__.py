{
    "name": "Amazon SP-API Connector: Pricing",
    "version": "19.0.1.1.0",
    "category": "Sales/Sales",
    "summary": "Manage Amazon product listings and sync prices via SP-API",
    "author": "Ledo, Odoo Community Association (OCA)",
    "website": "https://github.com/OCA/connector-amazon",
    "license": "AGPL-3",
    "depends": [
        "connector_amazon_sale",
    ],
    "data": [
        "security/ir.model.access.csv",
        "data/ir_cron.xml",
        "views/amz_listing_views.xml",
        "views/amz_price_history_views.xml",
        "views/amz_backend_views.xml",
    ],
    "maintainers": ["dnplkndll"],
    "development_status": "Beta",
    "external_dependencies": {
        "python": ["python-amazon-sp-api"],
    },
    "installable": True,
}
