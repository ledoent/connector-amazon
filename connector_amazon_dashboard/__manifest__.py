{
    "name": "Amazon SP-API Connector: Dashboard",
    "version": "19.0.1.2.0",
    "category": "Sales/Sales",
    "summary": "Health and KPI dashboard across the Amazon connector suite",
    "author": "Ledo, Odoo Community Association (OCA)",
    "website": "https://github.com/OCA/connector-amazon",
    "license": "AGPL-3",
    "depends": [
        "connector_amazon_sale",
        "connector_amazon_pricing",
        "connector_amazon_repricing",
        "connector_amazon_inventory",
        "connector_amazon_stock",
        "connector_amazon_payment",
        "connector_amazon_return",
        "connector_amazon_fba",
        "connector_amazon_fees",
    ],
    "data": [
        "security/ir.model.access.csv",
        "views/amz_dashboard_views.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "connector_amazon_dashboard/static/src/scss/amz_dashboard.scss",
        ],
    },
    "maintainers": ["dnplkndll"],
    "development_status": "Beta",
    "installable": True,
}
