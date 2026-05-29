{
    "name": "Amazon SP-API Connector: Settlements",
    "version": "19.0.1.0.1",
    "category": "Accounting/Accounting",
    "summary": "Pull Amazon settlement groups and generate Odoo journal entries",
    "author": "Ledo, Odoo Community Association (OCA)",
    "website": "https://github.com/OCA/connector-amazon",
    "license": "AGPL-3",
    "depends": ["connector_amazon_sale", "account"],
    "data": [
        "security/ir.model.access.csv",
        "views/amz_settlement_views.xml",
        "views/amz_backend_views.xml",
        "data/ir_cron.xml",
    ],
    "maintainers": ["dnplkndll"],
    "development_status": "Beta",
    "installable": True,
}
