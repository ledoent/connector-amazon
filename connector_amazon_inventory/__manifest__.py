{
    "name": "Amazon SP-API Connector: Inventory",
    "version": "19.0.1.0.0",
    "category": "Inventory/Inventory",
    "summary": "Push FBM stock quantities to Amazon listings via SP-API",
    "author": "Ledo, Odoo Community Association (OCA)",
    "website": "https://github.com/OCA/connector-amazon",
    "license": "AGPL-3",
    "depends": [
        "connector_amazon_pricing",
        "stock",
    ],
    "data": [
        "data/ir_cron.xml",
        "views/amz_listing_views.xml",
        "views/amz_backend_views.xml",
    ],
    "maintainers": ["dnplkndll"],
    "development_status": "Beta",
    "external_dependencies": {
        "python": ["python-amazon-sp-api"],
    },
    "installable": True,
}
