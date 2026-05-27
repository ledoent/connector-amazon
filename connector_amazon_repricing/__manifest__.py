{
    "name": "Amazon SP-API Connector: Real-Time Repricing",
    "version": "19.0.1.0.0",
    "summary": "Buy-box change feed via SQS → competitive repricing",
    "category": "Sales/Sales",
    "author": "Ledo, Odoo Community Association (OCA)",
    "website": "https://github.com/OCA/connector-amazon",
    "license": "AGPL-3",
    "development_status": "Beta",
    "depends": ["connector_amazon_pricing"],
    "external_dependencies": {"python": ["boto3", "python-amazon-sp-api"]},
    "data": [
        "data/ir_cron.xml",
        "views/amz_backend_views.xml",
    ],
    "maintainers": ["dnplkndll"],
    "installable": True,
}
