This module flags merchant-fulfilled (MFN) Amazon orders that are in danger of
missing Amazon's **ship-by cutoff** — before they turn into late-shipment
defects.

It captures each order's `LatestShipDate` from the SP-API and continuously
classifies open merchant orders into a single **ship risk** state:

- **Overdue** — the ship-by cutoff has already passed and the order is still unshipped.
- **Stock Blocked** — the delivery picking can't be fully reserved (out of stock / not ready), so it can't ship regardless of the clock.
- **At Risk** — within the configured number of hours of the cutoff.
- **On Track** — comfortably ahead, stock ready.

An **At-Risk Shipments** list (sorted by cutoff) surfaces everything that needs
attention, and the risk shows as a colour-coded badge on every order.
