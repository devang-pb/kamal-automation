#!/usr/bin/env python3
"""Run all 6 Shopify price comparisons using curl_cffi to bypass Cloudflare.

Uses Chrome TLS fingerprint impersonation to avoid bot detection.
Processes stores sequentially, products within each store with 6 threads.
"""

import csv
import os
import time
from concurrent.futures import ThreadPoolExecutor
from threading import Lock, local

from curl_cffi import requests as cffi_requests

OUTPUT_DIR = os.environ.get("OUTPUT_DIR", "output")
CATALOG = os.path.join(OUTPUT_DIR, "catalog.csv")
MAX_WORKERS = 6

STORES = [
    ("Cosmetic", "https://cosmetic.cl", "compare_cosmetic.csv"),
    ("Elite Perfumes", "https://eliteperfumes.cl", "compare_elite.csv"),
    ("Lodoro", "https://www.lodoro.cl", "compare_lodoro.csv"),
    ("Multimarcas Perfumes", "https://multimarcasperfumes.cl", "compare_multimarcas.csv"),
    ("Productos de Lujo", "https://productosdelujo.cl", "compare_productos.csv"),
    ("Yauras", "https://yauras.cl", "compare_yauras.csv"),
]

_thread_local = local()


def get_session():
    s = getattr(_thread_local, "session", None)
    if s is None:
        s = cffi_requests.Session(impersonate="chrome")
        _thread_local.session = s
    return s


def request_with_retry(url, params=None):
    for attempt in range(5):
        try:
            r = get_session().get(url, params=params, timeout=30)
            if r.status_code == 429:
                wait = 10 * (attempt + 1)
                time.sleep(wait)
                continue
            return r
        except Exception:
            if attempt < 4:
                time.sleep(5 * (attempt + 1))
            else:
                return None
    return None


def read_catalog():
    rows = []
    with open(CATALOG, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fnames = reader.fieldnames or []

        def pick(*candidates):
            for c in candidates:
                if c in fnames:
                    return c
            return None

        bc_key = pick("ean", "Bar Code", "Barcode", "BARCODE", "SKU")
        name_key = pick("name", "Name", "title")
        price_key = pick("Price", "price")

        for r in reader:
            bc = str(r[bc_key]).strip()
            if not bc:
                continue
            name = str(r[name_key]).strip()
            rows.append((bc, name))
    return rows


def lookup(site_url, barcode, product_cache, cache_lock):
    # Search
    r = request_with_retry(
        f"{site_url}/search/suggest.json",
        params={
            "q": barcode,
            "resources[type]": "product",
            "resources[limit]": 10,
            "resources[options][unavailable_products]": "show",
            "resources[options][fields]": "variants.barcode,variants.sku,title,vendor",
        },
    )
    if r is None or r.status_code != 200:
        return ("", "")

    products = r.json().get("resources", {}).get("results", {}).get("products", []) or []

    for p in products:
        handle = p.get("handle")
        if not handle:
            continue

        with cache_lock:
            if handle in product_cache:
                prod = product_cache[handle]
            else:
                prod = None

        if prod is None:
            pr = request_with_retry(f"{site_url}/products/{handle}.js")
            if pr and pr.status_code == 200:
                prod = pr.json()
                with cache_lock:
                    product_cache[handle] = prod
            else:
                with cache_lock:
                    product_cache[handle] = {}
                continue

        for v in prod.get("variants", []):
            if str(v.get("barcode") or "").strip() == barcode:
                price = int(v["price"] / 100)
                stock = "In Stock" if v.get("available") else "Out of Stock"
                return (price, stock)

    return ("", "")


def run_store(name, site_url, output_file, catalog):
    total = len(catalog)
    product_cache = {}
    cache_lock = Lock()
    out_path = os.path.join(OUTPUT_DIR, output_file)

    print(f"  [{name}] Starting — {total} products, {MAX_WORKERS} workers", flush=True)
    t0 = time.time()

    def process(item):
        barcode, pname = item
        return (barcode, pname, *lookup(site_url, barcode, product_cache, cache_lock))

    found = 0
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["ean", f"{name} Price", f"{name} Availability"])

        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            for i, (barcode, pname, price, stock) in enumerate(
                executor.map(process, catalog), 1
            ):
                w.writerow([barcode, price, stock])
                if price != "":
                    found += 1
                if i % 200 == 0:
                    print(f"  [{name}] {i}/{total} ({found} found)", flush=True)

    dur = time.time() - t0
    print(f"  [{name}] Done — {found}/{total} found in {dur:.0f}s", flush=True)


def main():
    catalog = read_catalog()
    print(f"Loaded {len(catalog)} products from catalog", flush=True)

    for name, url, outfile in STORES:
        # Reset thread-local sessions between stores
        _thread_local.__dict__.clear()
        run_store(name, url, outfile, catalog)

    print("All 6 Shopify compares done!", flush=True)


if __name__ == "__main__":
    main()
