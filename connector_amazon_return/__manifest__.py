{
    "name": "Amazon SP-API Connector: Returns",
    "version": "19.0.1.0.0",
    "category": "Sales/Sales",
    "summary": "Ingest Amazon MFN returns, restock them, and issue credit notes",
    "author": "Ledo, Odoo Community Association (OCA)",
    "website": "https://github.com/OCA/connector-amazon",
    "license": "AGPL-3",
    "depends": ["connector_amazon_stock", "connector_amazon_payment"],
    "data": [
        "security/ir.model.access.csv",
        "views/amz_return_views.xml",
        "views/amz_backend_views.xml",
        "data/ir_cron.xml",
    ],
    "maintainers": ["dnplkndll"],
    "development_status": "Beta",
    "installable": True,
}
