#!/usr/bin/env python3
"""Upload catalog_costanera.csv inventory to the Procwise platform."""

import csv
import logging
import os
import sys
from pathlib import Path

import requests
from dotenv import load_dotenv

from inventory_diff import InventoryDiff, fetch_current_inventory, compute_diff

load_dotenv()

BASE_URL = "https://procwise.purpleblock.ai"
CSV_PATH = Path(os.environ.get("OUTPUT_DIR", Path(__file__).parent / "output")) / "catalog_costanera.csv"
CSV_COLUMNS = ["ean", "sku", "name", "stock", "price", "avg_cost"]
WAREHOUSE_ID = "f49de329-e41d-4920-8194-94c4facfaa9d"

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
        sys.exit(1)

    resp = session.post(
        f"{BASE_URL}/api/auth/login",
        json={"email": email, "password": password},
    )
    resp.raise_for_status()
    data = resp.json()
    if not data.get("success"):
        log.error("Login failed: %s", data)
        sys.exit(1)
    log.info("Logged in (userId: %s)", data["userId"])


def send_column_map(session: requests.Session, rows: list[dict]) -> None:
    sample_data = [
        [row[col] for col in CSV_COLUMNS] for row in rows[:5]
    ]
    resp = session.post(
        f"{BASE_URL}/api/inventory-column-map",
        json={"columns": CSV_COLUMNS, "sampleData": sample_data},
    )
    resp.raise_for_status()
    log.info("Column map accepted: %s", resp.json())


def build_items(rows: list[dict]) -> list[dict]:
    items = []
    for row in rows:
        cost = round(float(row["avg_cost"]))
        items.append({
            "name": row["name"],
            "ean": row["ean"],
            "sku": row["sku"],
            "price": int(row["price"]),
            "stock": int(row["stock"]),
            "cost": cost,
            "costWithTax": round(cost * 1.19, 2),
        })
    return items


def upload_inventory(session: requests.Session, items: list[dict]) -> None:
    resp = session.post(
        f"{BASE_URL}/api/inventory",
        json=items,
        headers={"X-Warehouse-Id": WAREHOUSE_ID},
    )
    resp.raise_for_status()
    data = resp.json()
    if data.get("success"):
        log.info("Upload successful: %s", data["message"])
    else:
        log.error("Upload failed: %s", data)
        sys.exit(1)


def main() -> InventoryDiff | None:
    if not CSV_PATH.exists():
        log.error("CSV not found: %s", CSV_PATH)
        sys.exit(1)

    with open(CSV_PATH, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    log.info("Read %d items from %s", len(rows), CSV_PATH.name)

    items = build_items(rows)

    session = requests.Session()
    login(session)

    try:
        old_items = fetch_current_inventory(session, warehouse_id=WAREHOUSE_ID)
        diff = compute_diff(old_items, items, warehouse="Costanera")
    except Exception as e:
        log.warning("Could not compute diff: %s", e)
        diff = None

    send_column_map(session, rows)
    upload_inventory(session, items)
    return diff


if __name__ == "__main__":
    main()
