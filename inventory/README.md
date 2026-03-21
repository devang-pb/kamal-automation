# Inventory Pipeline

Runs on AWS Lambda twice daily (8:30 AM & 4:30 PM Chile time). Pulls inventory data from BSale, generates a catalog, and uploads it to ProcWise.

## Execution Order

```
pull_costs.py → generate_catalog.py → upload_inventory.py
```

## Scripts

### `pull_costs.py` — Step 1: Scrape Costs
- Uses Playwright (headless Chromium) to login to BSale at `account.bsale.dev`
- Selects company cpn 67758 (SILK PERFUMES), navigates to Stock module
- Captures `bsale-session` cookie from `stock.bsale.app`
- Paginates through `stock.bsale.app/gateway/stock/report.json` (office 1 / Gorbea, 50 items/page)
- Extracts: barcode, averageUnitNetCost, variantDescription (brand)
- **Output:** `output/costs.csv` — columns: `ean`, `avg_cost`, `brand` (~3963 rows)

### `generate_catalog.py` — Step 2: Build Catalog
- Uses BSale REST API (token auth via `BSALE_API_TOKEN`)
- Fetches 3 endpoints:
  - `/v1/stocks.json?officeid=1` → stock quantities at Gorbea (keeps qty > 0)
  - `/v1/price_lists/2/details.json` → base price list (gross prices with tax)
  - `/v1/variants.json?expand=[product]` → EAN, SKU, product name
- Joins with `costs.csv` by EAN to add avg_cost + brand
- **Output:** `output/catalog.csv` — columns: `ean`, `sku`, `name`, `stock`, `price`, `avg_cost`, `brand`

### `upload_inventory.py` — Step 3: Upload to ProcWise
- Logs into ProcWise (`procwise.purpleblock.ai`) with email/password
- Sends column map (first 5 rows as sample)
- POSTs full inventory with `costWithTax = avg_cost * 1.19` (Chilean IVA)

## Supporting Modules

### `bsale_session.py`
Playwright-based login automation for BSale. Navigates: login → company selection → Stock module → extracts `bsale-session` cookie. Used by `pull_costs.py`.

### `bsale_client.py`
HTTP client for the BSale REST API (`api.bsale.cl`). Handles:
- Token auth (header: `access_token`)
- Auto-pagination (50 items/page)
- Rate limiting (8 requests/second)
- Retries with exponential backoff (429, 5xx, connection errors)

### `lambda_handler.py`
AWS Lambda entry point. Configures CloudWatch logging, sets `OUTPUT_DIR=/tmp/output`, runs the 3 pipeline scripts in sequence. Returns JSON with success/error status.

## Costanera Variants

- `pull_costs_costanera.py` — Same as `pull_costs.py` but for the Costanera warehouse
- `generate_catalog_costanera.py` — Same as `generate_catalog.py` but for the Costanera warehouse

## Environment Variables

| Variable | Used by |
|----------|---------|
| `BSALE_EMAIL` / `BSALE_PASSWORD` | `pull_costs.py` (Playwright login) |
| `BSALE_API_TOKEN` / `BSALE_BASE_URL` | `generate_catalog.py` (REST API) |
| `PROCWISE_EMAIL` / `PROCWISE_PASSWORD` | `upload_inventory.py` |
| `OUTPUT_DIR` | All scripts (defaults to `output/`, Lambda uses `/tmp/output`) |
| `PLAYWRIGHT_BROWSERS_PATH` | Lambda container (set to `/opt/pw-browsers`) |
