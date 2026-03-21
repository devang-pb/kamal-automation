#!/usr/bin/env python3
"""Pull average unit costs from BSale's stock report endpoint for Costanera office.

Uses the internal stock.bsale.app endpoint (same as the "Stock Actual" UI)
to fetch cost data in bulk, instead of one API call per variant.

Outputs: output/costs_costanera.csv  (ean, avg_cost)

Auth: Playwright auto-login using BSALE_EMAIL / BSALE_PASSWORD from .env.
"""

import csv
import logging
import os
import sys
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

OUTPUT_DIR = Path(__file__).parent / "output"
REPORT_URL = "https://stock.bsale.app/gateway/stock/report.json"
COSTANERA_OFFICE_ID = 6
PAGE_LIMIT = 50

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def make_session(cookie_value):
    """Build a requests.Session with the bsale-session cookie."""
    session = requests.Session()
    session.headers.update({
        "Accept": "application/json, text/plain, */*",
    })
    session.cookies.set("bsale-session", cookie_value, domain="stock.bsale.app")
    return session


def fetch_all_rows(session):
    """Paginate through the stock report and return all row data."""
    all_rows = []
    offset = 0
    total_count = None

    while True:
        params = {
            "groupOffices": 0,
            "officeId": COSTANERA_OFFICE_ID,
            "minAvailable": "0.0000001",
            "limit": PAGE_LIMIT,
            "offset": offset,
        }
        for attempt in range(3):
            try:
                resp = session.get(REPORT_URL, params=params)
                break
            except requests.exceptions.ConnectionError as e:
                if attempt < 2:
                    logger.warning("Connection error, retrying in 2s...")
                    time.sleep(2)
                else:
                    raise
        if resp.status_code == 401:
            logger.error("Session cookie expired or invalid.")
            sys.exit(1)
        resp.raise_for_status()
        data = resp.json().get("data", {})

        if total_count is None:
            total_count = int(data.get("totalCount", 0))
            logger.info("Total products in report: %d", total_count)

        body_rows = data.get("bodyRows", [])
        for row in body_rows:
            row_data = extract_row_data(row)
            if row_data:
                all_rows.append(row_data)

        offset += PAGE_LIMIT
        logger.info("  Fetched %d/%d", min(offset, total_count), total_count)

        if offset >= total_count:
            break

    return all_rows


def extract_row_data(row):
    """Extract ean and avg_cost from a bodyRow's fields."""
    fields = row.get("fields", [])
    for field in fields:
        if field.get("hash") == "unit_cost":
            value = field.get("value", {})
            if isinstance(value, dict):
                props = value.get("props", {})
                inner = props.get("row", {})
                barcode = inner.get("barcode", "")
                avg_cost = inner.get("averageUnitNetCost")
                if barcode and avg_cost is not None:
                    return {"ean": str(barcode).strip(), "avg_cost": avg_cost}
    return None


def main():
    load_dotenv()

    from bsale_session import get_session_cookie_from_env
    cookie = get_session_cookie_from_env()

    session = make_session(cookie)

    rows = fetch_all_rows(session)
    logger.info("Extracted %d rows with barcode + cost data", len(rows))

    # Deduplicate by EAN — keep first occurrence
    seen = set()
    unique_rows = []
    for r in rows:
        ean = r["ean"]
        if ean not in seen:
            seen.add(ean)
            unique_rows.append(r)
    logger.info("Unique EANs: %d", len(unique_rows))

    # Write CSV
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    costs_path = OUTPUT_DIR / "costs_costanera.csv"
    with open(costs_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["ean", "avg_cost"])
        writer.writeheader()
        writer.writerows(unique_rows)

    print("Wrote %d rows to %s" % (len(unique_rows), costs_path))


if __name__ == "__main__":
    main()
