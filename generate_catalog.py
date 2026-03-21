#!/usr/bin/env python3
"""Generate catalog.csv directly from BSale API.

Fetches only Gorbea-office stock with base price list pricing.
"""

import csv
import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from bsale_client import BsaleClient

OUTPUT_DIR = Path(os.environ.get("OUTPUT_DIR", Path(__file__).parent / "output"))
GORBEA_OFFICE_ID = 1
BASE_PRICE_LIST_ID = 2

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def load_costs_by_ean() -> dict:
    """Load EAN -> {avg_cost, brand} mapping from costs.csv if it exists."""
    costs_path = OUTPUT_DIR / "costs.csv"
    if not costs_path.exists():
        return {}
    costs = {}
    with open(costs_path, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            ean = row.get("ean", "").strip()
            avg_cost = row.get("avg_cost", "")
            brand = row.get("brand", "").strip()
            if ean and avg_cost:
                costs[ean] = {"avg_cost": float(avg_cost), "brand": brand}
    return costs


def main():
    load_dotenv()
    token = os.getenv("BSALE_API_TOKEN")
    if not token:
        print("ERROR: BSALE_API_TOKEN not found in .env file.")
        sys.exit(1)

    base_url = os.getenv("BSALE_BASE_URL", "https://api.bsale.cl")
    client = BsaleClient(token, base_url)

    # 1. Stocks: server-side filtered to Gorbea office only
    raw_stocks = client.get_stocks_by_office(GORBEA_OFFICE_ID)
    gorbea_stock = {}
    for s in raw_stocks:
        variant = s.get("variant", {}) or {}
        vid = int(variant.get("id", 0)) if isinstance(variant, dict) else 0
        qty = float(s.get("quantityAvailable", 0))
        if qty > 0:
            gorbea_stock[vid] = int(qty)
    logger.info(f"Gorbea in-stock variants: {len(gorbea_stock)}")

    # 2. Price details: only the BASE price list
    raw_prices = client.get_price_list_details(BASE_PRICE_LIST_ID)
    base_prices = {}
    for pd in raw_prices:
        variant = pd.get("variant", {}) or {}
        vid = int(variant.get("id", 0)) if isinstance(variant, dict) else 0
        gross = float(pd.get("variantValueWithTaxes", 0) or 0)
        base_prices[vid] = int(gross)
    logger.info(f"Base price list entries: {len(base_prices)}")

    # 3. Variants: with product expanded (gives us EAN, SKU, product name)
    raw_variants = client.get_variants_with_product()
    variant_info = {}
    for v in raw_variants:
        vid = v.get("id", 0)
        product = v.get("product", {}) or {}
        product_name = ""
        if isinstance(product, dict):
            product_name = product.get("name", "")
        variant_info[vid] = {
            "ean": v.get("barCode", ""),
            "sku": v.get("code", ""),
            "name": product_name or v.get("description", ""),
        }
    logger.info(f"Total variants: {len(variant_info)}")

    # 4. Costs: load from costs.csv (produced by pull_costs.py)
    ean_costs = load_costs_by_ean()
    if ean_costs:
        logger.info(f"Loaded {len(ean_costs)} costs from costs.csv")
    else:
        logger.info("No costs.csv found — run pull_costs.py first to include avg_cost")

    # 5. Join: only variants in stock at Gorbea AND with a base price
    fieldnames = ["ean", "sku", "name", "stock", "price"]
    if ean_costs:
        fieldnames.extend(["avg_cost", "brand"])

    rows = []
    for vid, qty in gorbea_stock.items():
        price = base_prices.get(vid)
        if price is None:
            continue
        info = variant_info.get(vid)
        if info is None:
            continue
        row = {
            "ean": info["ean"],
            "sku": info["sku"],
            "name": info["name"],
            "stock": qty,
            "price": price,
        }
        if ean_costs:
            cost_data = ean_costs.get(info["ean"])
            row["avg_cost"] = cost_data["avg_cost"] if cost_data else ""
            row["brand"] = cost_data["brand"] if cost_data else ""
        rows.append(row)

    rows.sort(key=lambda r: r["name"])

    # 6. Write CSV
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    catalog_path = OUTPUT_DIR / "catalog.csv"
    with open(catalog_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print(f"Wrote {len(rows)} rows to {catalog_path}")


if __name__ == "__main__":
    main()
