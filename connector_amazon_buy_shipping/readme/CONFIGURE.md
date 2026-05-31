1. **Set the Buy Shipping defaults per backend.** Open **Amazon → Configuration →
   Backends** and fill the *Buy Shipping Defaults* section:
   - **Default Package Weight** + **unit** (Ounces / Grams) — pre-fills the wizard
     when the moved products carry no weight.
   - **Default L × W × H** + **unit** (Inches / Centimeters) — the package
     dimensions pre-filled into the wizard.
   - **Label Format** — **PNG**, **PDF**, or **ZPL** (203 dpi). This is the format
     Amazon returns and the format of the stored label attachment, so match it to
     your printer (ZPL for thermal label printers, PDF/PNG for office printers).

2. **Product weights.** The wizard's weight defaults to the sum of the moved
   products' **Weight × quantity**; set product weights for accurate, per-order
   pre-fills (the backend default is only the fallback).

3. **Ship-from address.** Labels ship from the backend **Warehouse** partner address
   (falling back to the company address), so ensure the warehouse address is
   complete and accurate.

4. **No scheduled action.** Buying a label is entirely user-driven from the delivery;
   there is no cron to enable. Buying the label also confirms the shipment to Amazon,
   so these deliveries skip the separate ConfirmShipment push automatically.
