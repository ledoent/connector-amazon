{
    "name": "Amazon SP-API Connector: Multi-Channel Fulfillment",
    "version": "19.0.1.0.0",
    "category": "Sales/Sales",
    "summary": "Fulfill non-Amazon orders from FBA stock via Multi-Channel Fulfillment",
    "author": "Ledo, Odoo Community Association (OCA)",
    "website": "https://github.com/OCA/connector-amazon",
    "license": "AGPL-3",
    "depends": [
        "connector_amazon_fba",
        "connector_amazon_stock",
    ],
    "data": [
        "security/ir.model.access.csv",
        "data/ir_cron.xml",
        "views/amz_fulfillment_order_views.xml",
        "views/stock_picking_views.xml",
        "views/amz_backend_views.xml",
    ],
    "maintainers": ["dnplkndll"],
    "development_status": "Beta",
    "external_dependencies": {"python": ["python-amazon-sp-api"]},
    "installable": True,
}
