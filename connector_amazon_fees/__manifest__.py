{
    "name": "Amazon SP-API Connector: Fees & Profitability",
    "version": "19.0.1.0.0",
    "category": "Sales/Sales",
    "summary": "Estimate Amazon referral + FBA fees per SKU and track net margin",
    "author": "Ledo, Odoo Community Association (OCA)",
    "website": "https://github.com/OCA/connector-amazon",
    "license": "AGPL-3",
    "depends": [
        "connector_amazon_pricing",
    ],
    "data": [
        "data/ir_cron.xml",
        "views/amz_fees_views.xml",
    ],
    "maintainers": ["dnplkndll"],
    "development_status": "Beta",
    "external_dependencies": {
        "python": ["python-amazon-sp-api"],
    },
    "installable": True,
}
