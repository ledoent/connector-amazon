{
    "name": "Amazon SP-API Connector",
    "version": "19.0.1.0.0",
    "category": "Sales/Sales",
    "summary": "Base connector for Amazon Selling Partner API",
    "author": "Ledo, Odoo Community Association (OCA)",
    "website": "https://github.com/OCA/connector-amazon",
    "license": "AGPL-3",
    "depends": [
        "queue_job",
        "sale",
        "delivery",
    ],
    "external_dependencies": {
        "python": ["sp_api"],
    },
    "data": [
        "security/amz_security.xml",
        "security/ir.model.access.csv",
        "data/ir_cron.xml",
        "views/amz_backend_views.xml",
        "views/amz_order_views.xml",
        "views/res_config_settings_views.xml",
    ],
    "maintainers": ["dnplkndll"],
    "development_status": "Alpha",
    "installable": True,
}
