import csv
import json
import os
import random
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from html import unescape
from urllib.parse import urljoin

import requests
from requests.adapters import HTTPAdapter

SITE_NAME = "Sairam"
BASE_URL = "https://sairam.cl"
CATEGORY_PATH = "/perfume"
OUT_CSV = "scrape_sairam.csv"

MAX_WORKERS = int(os.getenv("SCRAPER_WORKERS", "12"))
MAX_CATEGORY_PAGES = int(os.getenv("SCRAPER_MAX_CATEGORY_PAGES", "300"))
REQUEST_TIMEOUT = 25
MAX_RETRIES = 6
MIN_SLEEP = float(os.getenv("SCRAPER_MIN_SLEEP", "0.02"))
MAX_SLEEP = float(os.getenv("SCRAPER_MAX_SLEEP", "0.12"))
HTTP_POOL_SIZE = int(os.getenv("SCRAPER_HTTP_POOL", str(max(32, MAX_WORKERS * 4))))

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; PurpleBlockCatalogBot/1.0)",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "es-CL,es;q=0.9,en;q=0.8",
}

JSONLD_RE = re.compile(
    r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
    re.I | re.S,
)

IDENTIFIER_KEYS = (
    "productID",
    "gtin13",
    "gtin14",
    "gtin12",
    "gtin8",
    "gtin",
    "barcode",
    "sku",
    "mpn",
)

LISTING_LINK_CLASSES = ("product-block__anchor", "product-block__name")
RESERVED_SINGLE_SEGMENT_PATHS = {
    "search",
    "cart",
    "checkout",
    "login",
    "account",
    "accounts",
    "register",
    "customer",
    "perfume",
    "marcas",
    "accesorios",
    "mayorista",
    "contact",
    "sucursales",
    "robots.txt",
}
DECLARED_TOTAL_RE = re.compile(
    r"muestra\s*[0-9.,]+\s*de\s*([0-9.,]+)\s*productos",
    re.I,
)


def format_seconds(seconds: float | None) -> str:
    if seconds is None:
        return "?"
    total = max(0, int(seconds))
    minutes, sec = divmod(total, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}h{minutes:02d}m{sec:02d}s"
    if minutes:
        return f"{minutes}m{sec:02d}s"
    return f"{sec}s"


def fetch(session: requests.Session, url: str) -> str:
    last_exc = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = session.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
            if response.status_code in (429, 500, 502, 503, 504):
                backoff = min(3.5, 0.35 * (2 ** (attempt - 1))) + random.uniform(0, 0.25)
                time.sleep(backoff)
                continue
            response.raise_for_status()
            return response.text
        except Exception as exc:
            last_exc = exc
            backoff = min(3.5, 0.35 * (2 ** (attempt - 1))) + random.uniform(0, 0.25)
            time.sleep(backoff)
    raise RuntimeError(f"Failed fetching {url}: {last_exc}")


def safe_json_loads(text: str):
    text = text.strip()
    try:
        return json.loads(text)
    except Exception:
        text = re.sub(r",\s*([}\]])", r"\1", text)
        return json.loads(text)


def iter_product_jsonld_objects(html: str):
    for match in JSONLD_RE.finditer(html):
        blob = match.group(1).strip()
        if not blob:
            continue
        try:
            data = safe_json_loads(blob)
        except Exception:
            continue

        stack = []
        if isinstance(data, dict):
            stack.append(data)
        elif isinstance(data, list):
            stack.extend([x for x in data if isinstance(x, (dict, list))])

        while stack:
            current = stack.pop()
            if isinstance(current, list):
                stack.extend([x for x in current if isinstance(x, (dict, list))])
                continue
            if not isinstance(current, dict):
                continue
            if isinstance(current.get("@graph"), list):
                stack.extend([x for x in current["@graph"] if isinstance(x, (dict, list))])

            obj_type = current.get("@type")
            is_product = obj_type == "Product" or (
                isinstance(obj_type, list) and "Product" in obj_type
            )
            if is_product:
                yield current


def parse_product_row_from_html(html: str, page_url: str) -> dict | None:
    for product in iter_product_jsonld_objects(html):
        offers = product.get("offers")
        if isinstance(offers, list):
            offers = next((x for x in offers if isinstance(x, dict)), None)
        if not isinstance(offers, dict):
            offers = {}

        name = product.get("name")
        if isinstance(name, str):
            name = name.strip()
        elif name is None:
            name = ""
        else:
            name = str(name).strip()

        identifier = ""
        for key in IDENTIFIER_KEYS:
            value = product.get(key)
            if value is not None and str(value).strip():
                identifier = str(value).strip()
                break

        price = offers.get("price")
        availability = offers.get("availability")

        return {
            "name": name,
            "gtin_or_equivalent": identifier,
            "price": "" if price is None else str(price).strip(),
            "availability": "" if availability is None else str(availability).strip(),
        }
    return None


def extract_links_by_class(html: str, class_token: str) -> list[str]:
    token = re.escape(class_token)
    pattern = re.compile(
        rf'<a[^>]*class=["\'][^"\']*{token}[^"\']*["\'][^>]*href=["\']([^"\']+)["\']'
        rf'|<a[^>]*href=["\']([^"\']+)["\'][^>]*class=["\'][^"\']*{token}[^"\']*["\']',
        re.I,
    )

    links = []
    for match in pattern.finditer(html):
        href = match.group(1) or match.group(2) or ""
        href = unescape(href).strip()
        if href:
            links.append(href)
    return links


def is_likely_product_path(path: str) -> bool:
    if not path.startswith("/"):
        return False
    if path.startswith("//"):
        return False
    clean = path.split("#", 1)[0].split("?", 1)[0].strip("/")
    if not clean:
        return False
    if "/" in clean:
        return False
    if "." in clean:
        return False
    if clean.lower() in RESERVED_SINGLE_SEGMENT_PATHS:
        return False
    return True


def extract_listing_product_urls(html: str) -> list[str]:
    raw_links = []
    for class_token in LISTING_LINK_CLASSES:
        raw_links.extend(extract_links_by_class(html, class_token))

    out = []
    seen = set()
    for href in raw_links:
        if not is_likely_product_path(href):
            continue
        absolute_url = urljoin(BASE_URL, href).split("#", 1)[0].split("?", 1)[0]
        if absolute_url not in seen:
            seen.add(absolute_url)
            out.append(absolute_url)
    return out


def parse_declared_total(html: str) -> int | None:
    match = DECLARED_TOTAL_RE.search(html)
    if not match:
        return None
    raw = match.group(1)
    digits = re.sub(r"[^0-9]", "", raw)
    return int(digits) if digits else None


def collect_category_product_urls(session: requests.Session) -> tuple[list[str], int | None]:
    all_product_urls = []
    seen_urls = set()
    declared_total = None
    no_new_streak = 0

    for page in range(1, MAX_CATEGORY_PAGES + 1):
        page_url = f"{BASE_URL}{CATEGORY_PATH}?page={page}"
        try:
            html = fetch(session, page_url)
        except Exception as exc:
            print(f"    Failed listing page {page}: {exc}")
            break

        if page == 1:
            declared_total = parse_declared_total(html)
            if declared_total is not None:
                print(f"    Category reports {declared_total} products")

        page_urls = extract_listing_product_urls(html)
        if not page_urls:
            print(f"    Page {page}: no product links found, stopping listing crawl")
            break

        new_count = 0
        for product_url in page_urls:
            if product_url in seen_urls:
                continue
            seen_urls.add(product_url)
            all_product_urls.append(product_url)
            new_count += 1

        if new_count == 0:
            no_new_streak += 1
        else:
            no_new_streak = 0

        print(
            f"    Listing page {page}: found {len(page_urls)} links, new={new_count},"
            f" cumulative={len(all_product_urls)}"
        )

        if declared_total is not None and len(all_product_urls) >= declared_total:
            print("    Reached declared category product total")
            break

        if no_new_streak >= 2:
            print("    No new product URLs for two consecutive pages, stopping listing crawl")
            break

    return all_product_urls, declared_total


def scrape_one_product(session: requests.Session, url: str) -> dict | None:
    time.sleep(random.uniform(MIN_SLEEP, MAX_SLEEP))
    html = fetch(session, url)
    return parse_product_row_from_html(html, page_url=url)


def scrape_product_pages(session: requests.Session, product_urls: list[str]) -> list[dict]:
    rows = []
    total_urls = len(product_urls)
    if total_urls == 0:
        return rows

    workers = min(MAX_WORKERS, total_urls)
    processed = 0
    scraped = 0
    errors = 0
    started = time.perf_counter()
    last_report_at = 0.0
    report_every = max(20, total_urls // 40)

    print(f"Scraping {total_urls} product pages with workers={workers}")

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [executor.submit(scrape_one_product, session, url) for url in product_urls]
        for future in as_completed(futures):
            processed += 1
            try:
                row = future.result()
            except Exception:
                errors += 1
                row = None

            if row:
                rows.append(row)
                scraped += 1

            now = time.perf_counter()
            if (
                processed == 1
                or processed == total_urls
                or processed % report_every == 0
                or now - last_report_at >= 1.5
            ):
                elapsed = now - started
                rate = processed / elapsed if elapsed > 0 else 0.0
                remaining = max(0, total_urls - processed)
                eta = remaining / rate if rate > 0 else None
                skipped = processed - scraped - errors
                pct = processed / total_urls * 100.0
                print(
                    f"    Progress: {processed}/{total_urls} ({pct:.1f}%)"
                    f" | products={scraped} | skipped={skipped} | errors={errors}"
                    f" | rate={rate:.1f}/s | eta={format_seconds(eta)}"
                )
                last_report_at = now

    return rows


def run() -> None:
    rows = []
    with requests.Session() as session:
        adapter = HTTPAdapter(pool_connections=HTTP_POOL_SIZE, pool_maxsize=HTTP_POOL_SIZE)
        session.mount("http://", adapter)
        session.mount("https://", adapter)

        print(f"[1/3] Collecting product URLs from {BASE_URL}{CATEGORY_PATH}")
        product_urls, declared_total = collect_category_product_urls(session)
        print(f"[2/3] Collected {len(product_urls)} unique product URLs")

        rows = scrape_product_pages(session, product_urls)
        print(f"[3/3] Extracted JSON-LD from {len(rows)} product pages")

        if declared_total is not None and len(product_urls) != declared_total:
            print(
                f"Warning: listing reported {declared_total} products,"
                f" but collected {len(product_urls)} URLs"
            )

    fieldnames = ["name", "gtin_or_equivalent", "price", "availability"]
    with open(OUT_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print(f"Done. Wrote {len(rows)} product rows to {OUT_CSV}")


if __name__ == "__main__":
    run()
