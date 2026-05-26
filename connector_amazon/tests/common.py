"""Shared fixtures and sandbox SP-API response payloads recorded from live calls."""

# GetOrders sandbox response (TEST_CASE_200)
SANDBOX_GET_ORDERS_PAYLOAD = {
    "CreatedBefore": "1.569521782042E9",
    "Orders": [
        {
            "AmazonOrderId": "902-1845936-5435065",
            "PurchaseDate": "1970-01-19T03:58:30Z",
            "LastUpdateDate": "1970-01-19T03:58:32Z",
            "OrderStatus": "Unshipped",
            "FulfillmentChannel": "MFN",
            "SalesChannel": "Amazon.com",
            "ShipServiceLevel": "Std US D2D Dom",
            "OrderTotal": {"CurrencyCode": "USD", "Amount": "11.01"},
            "NumberOfItemsShipped": 0,
            "NumberOfItemsUnshipped": 1,
            "MarketplaceId": "ATVPDKIKX0DER",
            "IsBusinessOrder": False,
            "IsPrime": False,
        },
        {
            "AmazonOrderId": "902-8745147-1934268",
            "PurchaseDate": "1970-01-19T03:58:30Z",
            "LastUpdateDate": "1970-01-19T03:58:32Z",
            "OrderStatus": "Unshipped",
            "FulfillmentChannel": "MFN",
            "SalesChannel": "Amazon.com",
            "OrderTotal": {"CurrencyCode": "USD", "Amount": "11.01"},
            "MarketplaceId": "ATVPDKIKX0DER",
            "IsBusinessOrder": False,
            "IsPrime": False,
        },
    ],
}

# GetOrderItems sandbox response (orderId=TEST_CASE_200)
SANDBOX_GET_ORDER_ITEMS_PAYLOAD = {
    "AmazonOrderId": "902-1845936-5435065",
    "OrderItems": [
        {
            "ASIN": "B00551Q3CS",
            "OrderItemId": "05015851154158",
            "SellerSKU": "NABetaASINB00551Q3CS",
            "Title": "B00551Q3CS [Card Book]",
            "QuantityOrdered": 1,
            "QuantityShipped": 0,
            "ItemPrice": {"CurrencyCode": "USD", "Amount": "10.00"},
            "ItemTax": {"CurrencyCode": "USD", "Amount": "1.01"},
            "IsGift": "false",
            "ConditionId": "New",
        }
    ],
}

# GetOrderAddress sandbox response (orderId=TEST_CASE_200)
SANDBOX_GET_ORDER_ADDRESS_PAYLOAD = {
    "AmazonOrderId": "902-1845936-5435065",
    "ShippingAddress": {
        "Name": "MFNIntegrationTestMerchant",
        "AddressLine1": "2201 WESTLAKE AVE",
        "City": "SEATTLE",
        "StateOrRegion": "WA",
        "PostalCode": "98121-2778",
        "CountryCode": "US",
        "Phone": "+1 480-386-0930 ext. 73824",
        "AddressType": "Commercial",
    },
}
