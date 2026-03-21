# Price Comparisons

Compares Kamal's inventory prices against 9 competitor sites. Requires `output/catalog.csv` from the inventory pipeline.

## Execution Order

```
Phase 1 (parallel):  compare_cosmetic/elite/lodoro/multimarcas/productos/yauras
Phase 2 (scrapers):  scrape_sairam/paris/lattafa → output/scrape_*.csv
Phase 3 (sequential): compare_sairam/paris/lattafa
Phase 4:             merge_comparisons.py
```

## Shopify Barcode Lookups (6 scripts)

All 6 are identical in logic, differing only in site URL and name:

| Script | Site |
|--------|------|
| `compare_cosmetic.py` | cosmetic.cl |
| `compare_elite.py` | eliteperfumes.cl |
| `compare_lodoro.py` | lodoro.cl |
| `compare_multimarcas.py` | multimarcasperfumes.cl |
| `compare_productos.py` | productosdelujo.cl |
| `compare_yauras.py` | yauras.cl |

### How they work
1. Read `output/catalog.csv` for the master product list
2. For each EAN, call Shopify predictive search: `{site}/search/suggest.json?q={barcode}`
3. For each result, fetch `{site}/products/{handle}.js` for full variant data
4. Match by exact barcode in variant list → extract price (centavos / 100) and availability
5. 12 concurrent threads with retry/backoff on 429 rate limits
6. **Output:** `output/compare_{site}.csv` — columns: `ean`, `{Site} Price`, `{Site} Availability`

## Fuzzy Name Matchers (3 scripts)

Handle suppliers that don't use standard barcodes. Each reads a scraped CSV and matches products by name.

### `compare_lattafa.py`
- **Input:** `output/scrape_lattafa.csv`
- **Two-phase matching:**
  - Phase 1: Exact barcode match (entries with numeric GTINs)
  - Phase 2: Token-based name matching with inverted index
- Strips Chirag-specific prefixes ("pure concentrated perfume oil", "body spray", etc.)
- Detects product type (fragrance, deodorant, ambiental, oil, set)
- Rejects cross-type matches (e.g. fragrance vs deodorant)
- Requires 65% product token overlap + fuzzy matching for typos
- One-to-one matching (greedy by score)
- **Output:** `output/compare_lattafa.csv`

### `compare_paris.py`
- **Input:** `output/scrape_paris.csv`
- Weighted multi-signal scorer:
  - Tokenizes names, detects brand/gender/concentration/size/tester/set
  - Filters by brand, gender, concentration, size, set compatibility
  - "High-info tokens" (rare, 3+ chars, freq <= 5) as a gate
  - Score = 41% weighted coverage (IDF) + 16% exact + 12% Jaccard + 17% core similarity + 8% full similarity + 6% brand + attribute bonuses
  - Thresholds vary by query token count (stricter for shorter names)
- **Output:** `output/compare_paris.csv`

### `compare_sairam.py`
- **Input:** `output/scrape_sairam.csv`
- Similar to Paris but tuned stricter:
  - Roman numeral support (I, II, III...)
  - "Critical tokens" (length >= 4, freq <= 15) as hard filter
  - Score = 43% weighted coverage + 20% exact + 12% Jaccard + 16% core + 5% full + 4% brand
  - Higher minimum thresholds: 0.82–0.95 depending on token count
- **Output:** `output/compare_sairam.csv`

## Merge (`merge_comparisons.py`)

- Reads `output/catalog.csv` + all 9 `output/compare_*.csv` files
- For each product: finds cheapest **in-stock** competitor price
- Calculates price gap % vs Kamal's price
- **Output:** `output/merged_comparisons.csv`
- Columns: `Bar Code`, `Name`, `Brand`, `Stock`, `My Price`, `Cheapest Price`, `Cheapest Site`, `Price Gap %`, then one column per competitor
