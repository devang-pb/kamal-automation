# Scrapers

Data collection scripts that fetch product/price data from external supplier sites. All use pure HTTP (requests + threads) — no browser required.

## Scrape Scripts

All three follow the same pattern: crawl category pages → collect product URLs → scrape each product page → extract JSON-LD structured data → write CSV.

### `scrape_sairam.py`
- **Site:** sairam.cl
- **Category:** `/perfume`
- **Link extraction:** CSS classes `product-block__anchor`, `product-block__name`
- **Output:** `output/scrape_sairam.csv`

### `scrape_paris.py`
- **Site:** parisperfumes.cl
- **Category:** `/perfumes-1`
- **Link extraction:** CSS class `product-image`
- **Output:** `output/scrape_paris.csv`

### `scrape_lattafa.py`
- **Site:** lattafaperfumes.cl
- **Category:** `/tienda/`
- **Link extraction:** All hrefs containing `/producto/`
- **Output:** `output/scrape_lattafa.csv`

### How they work
1. **Collect URLs:** Paginate through category listing (`?page=N`), extract product links by CSS class or URL pattern
2. **Scrape products:** Hit each product page with 12 concurrent workers, extract `application/ld+json` (JSON-LD) structured data
3. **Extract fields:** From JSON-LD Product object: `name`, `gtin_or_equivalent` (tries productID/gtin13/gtin/barcode/sku/mpn), `price`, `availability`
4. **Write CSV:** columns: `name`, `gtin_or_equivalent`, `price`, `availability`

### Config (env vars)
| Variable | Default | Description |
|----------|---------|-------------|
| `SCRAPER_WORKERS` | 12 | Concurrent threads |
| `SCRAPER_MAX_CATEGORY_PAGES` | 300 | Max listing pages to crawl |
| `SCRAPER_MIN_SLEEP` / `SCRAPER_MAX_SLEEP` | 0.02 / 0.12 | Random delay between requests |

## `download_excels.py`
Selenium automation to download Excel price lists from 7 Chilean wholesale sites:

| # | Site | Target File |
|---|------|-------------|
| 1 | yauras-mayorista.cl | `Yauras.xlsx` |
| 2 | cosmetic-distribucion.cl | `Cosmetic Mayorista.xlsx` |
| 3 | pdlbodega.cl | `Productos de Lujo VIP.xlsx` |
| 4 | eliteperfumes-mayorista.cl | `ElitePerfumes Mayorista.xlsx` |
| 5 | iconic-distribucion.cl | `Iconic Distribucion.xlsx` |
| 6 | elitebrands-mayorista.cl | `Elite Brands.xlsx` |
| 7 | silk-distribucion.cl | `Silk Mayorista.xlsx` |

**Requires:** Selenium, Chrome, `webdriver-manager`
**Output:** `downloads/{filename}.xlsx`
