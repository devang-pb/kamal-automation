import csv
import os
import time
from concurrent.futures import ThreadPoolExecutor
from threading import Lock, local

import requests

# =========================
# CONFIG — EDIT THESE
# =========================

MASTER_FILE = os.path.join(os.environ.get("OUTPUT_DIR", "output"), "missing_products.csv")
SITE_NAME = "Cosmetic"
SITE_URL = "https://cosmetic.cl"
OUTPUT_FILE = os.path.join(os.environ.get("OUTPUT_DIR", "output"), "compare_cosmetic.csv")

MAX_RETRIES = 5
MAX_WORKERS = max(1, int(os.getenv("COMPARE_MAX_WORKERS", "12")))

HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept": "application/json",
    "Accept-Language": "es-CL,es;q=0.9,en;q=0.8",
}

_thread_local = local()


# =========================
# INTERNAL HELPERS
# =========================

def read_master(path: str):
    rows = []
    with open(path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames or []

        def pick(*candidates):
            for c in candidates:
                if c in fieldnames:
                    return c
            return None

        bc_key = pick("ean", "Bar Code", "Barcode", "BARCODE", "SKU")
        name_key = pick("name", "Name", "title")

        if not bc_key or not name_key:
            raise ValueError(
                f"MASTER_FILE must have columns ean/Name (or equivalents). Found: {fieldnames}"
            )

        for r in reader:
            bc = str(r[bc_key]).strip()
            if not bc:
                continue

            name = str(r[name_key]).strip()
            rows.append((bc, name))

    return rows


def build_session() -> requests.Session:
    session = requests.Session()
    adapter = requests.adapters.HTTPAdapter(
        pool_connections=MAX_WORKERS,
        pool_maxsize=MAX_WORKERS,
    )
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session


def get_thread_session() -> requests.Session:
    session = getattr(_thread_local, "session", None)
    if session is None:
        session = build_session()
        _thread_local.session = session
    return session


def request_with_retry(session: requests.Session, url: str, params=None):
    for attempt in range(MAX_RETRIES):
        try:
            time.sleep(0.15)  # Throttle to avoid 429s
            r = session.get(url, params=params, headers=HEADERS, timeout=30)

            if r.status_code == 429:
                wait = 10 * (attempt + 1)
                print(f"  429 on {url}, backing off {wait}s")
                time.sleep(wait)
                continue

            return r
        except requests.exceptions.RequestException as e:
            if attempt < MAX_RETRIES - 1:
                wait = 5 * (attempt + 1)
                print(f"  Retry {attempt + 1}/{MAX_RETRIES} ({wait}s): {e}")
                time.sleep(wait)
            else:
                print(f"  Failed after {MAX_RETRIES} attempts: {e}")
                return None

    return None


def predictive_search_candidates(session: requests.Session, barcode: str):
    url = f"{SITE_URL}/search/suggest.json"
    params = {
        "q": barcode,
        "resources[type]": "product",
        "resources[limit]": 10,
        "resources[options][unavailable_products]": "show",
        "resources[options][fields]": "variants.barcode,variants.sku,title,vendor",
    }
    r = request_with_retry(session, url, params=params)
    if r is None or r.status_code != 200:
        return []

    data = r.json()
    return data.get("resources", {}).get("results", {}).get("products", []) or []


def fetch_product_js(
    session: requests.Session,
    handle: str,
    cache: dict,
    cache_lock: Lock,
):
    with cache_lock:
        if handle in cache:
            return cache[handle]

    url = f"{SITE_URL}/products/{handle}.js"
    r = request_with_retry(session, url)
    if r is None or r.status_code != 200:
        with cache_lock:
            cache[handle] = None
        return None

    data = r.json()
    with cache_lock:
        cache[handle] = data
    return data


def lookup_price_stock_by_barcode(barcode: str, product_cache: dict, cache_lock: Lock):
    session = get_thread_session()
    candidates = predictive_search_candidates(session, barcode)
    if not candidates:
        return ("", "")

    for p in candidates:
        handle = p.get("handle")
        if not handle:
            continue

        prod = fetch_product_js(session, handle, product_cache, cache_lock)
        if not prod:
            continue

        for v in prod.get("variants", []):
            if str(v.get("barcode") or "").strip() == barcode:
                price = int(v["price"] / 100)
                stock = "In Stock" if bool(v.get("available")) else "Out of Stock"
                return (price, stock)

    return ("", "")


# =========================
# MAIN
# =========================

def main():
    master = read_master(MASTER_FILE)
    total = len(master)

    product_cache = {}
    cache_lock = Lock()

    print(
        f"Comparing {total} products against {SITE_NAME} ({SITE_URL}) "
        f"with {MAX_WORKERS} workers..."
    )

    def process_row(row):
        barcode, name = row
        price, stock = lookup_price_stock_by_barcode(barcode, product_cache, cache_lock)
        return (barcode, name, price, stock)

    with open(OUTPUT_FILE, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["ean", f"{SITE_NAME} Price", f"{SITE_NAME} Availability"])

        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            for i, (barcode, name, price, stock) in enumerate(
                executor.map(process_row, master), 1
            ):
                w.writerow([barcode, price, stock])
                if i % 500 == 0 or i == total:
                    print(f"[{i}/{total}] processed")

    print(f"\nDone! {total} rows saved to {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
