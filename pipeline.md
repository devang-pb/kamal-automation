# Pipeline 1: Inventory (Lambda — runs daily at 8:30 AM & 4:30 PM Chile)

inventory/pull_costs.py        → scrapes cost + brand data from BSale stock report → output/costs.csv
inventory/generate_catalog.py  → builds full catalog from BSale API + costs       → output/catalog.csv
inventory/upload_inventory.py  → uploads catalog to ProcWise platform

# Pipeline 2: Price Comparisons (not yet automated)

## Phase 1: Shopify barcode lookups (6 sites, can run in parallel)
comparisons/compare_cosmetic.py      → output/compare_cosmetic.csv
comparisons/compare_elite.py         → output/compare_elite.csv
comparisons/compare_lodoro.py        → output/compare_lodoro.csv
comparisons/compare_multimarcas.py   → output/compare_multimarcas.csv
comparisons/compare_productos.py     → output/compare_productos.csv
comparisons/compare_yauras.py        → output/compare_yauras.csv

## Phase 2: Scrape 3 supplier catalogs (not yet implemented)
scrapers/scrape_sairam.py    → output/scrape_sairam.csv
scrapers/scrape_paris.py     → output/scrape_paris.csv
scrapers/scrape_lattafa.py   → output/scrape_lattafa.csv

## Phase 3: Fuzzy name matching against scraped data
comparisons/compare_sairam.py    → output/compare_sairam.csv
comparisons/compare_paris.py     → output/compare_paris.csv
comparisons/compare_lattafa.py   → output/compare_lattafa.csv

## Phase 4: Merge all 9 comparisons
comparisons/merge_comparisons.py → output/merged_comparisons.csv

# Other
scrapers/download_excels.py → fetches 7 supplier price list Excels into downloads/
