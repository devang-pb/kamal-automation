#!/usr/bin/env python3
"""Upload merged_comparisons.csv to the Procwise retail-intel endpoint."""

import csv
import logging
import os
import sys
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()

BASE_URL = "https://procwise.purpleblock.ai"
CSV_PATH = Path(os.environ.get("OUTPUT_DIR", Path(__file__).parent)) / "merged_comparisons.csv"

# CSV column → payload key mapping
COLUMN_MAP = {
    "Bar Code": "ean",
    "Name": "productName",
    "Brand": "brand",
    "Stock": "stock",
    "Price Gap %": "priceGap",
    "My Price": "myPrice",
    "Cheapest Price": "cheapestPrice",
    "Cheapest Site": "cheapestSite",
    "Cosmetic": "cosmetic",
    "Productos de Lujo": "productos",
    "Lodoro": "lodoro",
    "Multimarcas Perfumes": "multimarcas",
    "Elite Perfumes": "elitePerfumes",
    "Yauras": "yauras",
    "Lattafa": "lattafa",
    "Sairam": "sairam",
    "Paris": "paris",
}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
)
log = logging.getLogger(__name__)


def login(session: requests.Session) -> None:
    email = os.getenv("PROCWISE_EMAIL")
    password = os.getenv("PROCWISE_PASSWORD")
    if not email or not password:
        log.error("PROCWISE_EMAIL / PROCWISE_PASSWORD not set in .env")
        raise RuntimeError("Operation failed")

    resp = session.post(
        f"{BASE_URL}/api/auth/login",
        json={"email": email, "password": password},
    )
    resp.raise_for_status()
    data = resp.json()
    if not data.get("success"):
        log.error("Login failed: %s", data)
        raise RuntimeError("Operation failed")
    log.info("Logged in (userId: %s)", data["userId"])


def build_items(rows: list[dict]) -> list[dict]:
    items = []
    for row in rows:
        item = {}
        for csv_col, payload_key in COLUMN_MAP.items():
            item[payload_key] = row.get(csv_col, "") or "-"
        items.append(item)
    return items


def upload_retail_intel(session: requests.Session, items: list[dict]) -> None:
    resp = session.post(f"{BASE_URL}/api/retail-intel", json=items)
    resp.raise_for_status()
    data = resp.json()
    if data.get("success"):
        log.info("Upload successful: %s", data["message"])
    else:
        log.error("Upload failed: %s", data)
        raise RuntimeError("Operation failed")


def main() -> None:
    if not CSV_PATH.exists():
        log.error("CSV not found: %s", CSV_PATH)
        raise RuntimeError("Operation failed")

    with open(CSV_PATH, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    log.info("Read %d items from %s", len(rows), CSV_PATH.name)

    items = build_items(rows)

    session = requests.Session()
    login(session)
    upload_retail_intel(session, items)


if __name__ == "__main__":
    main()
