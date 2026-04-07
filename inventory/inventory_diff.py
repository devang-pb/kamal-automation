#!/usr/bin/env python3
"""Fetch current inventory from ProcWise and compute diff against new items."""

import logging
from dataclasses import dataclass, field

import requests

log = logging.getLogger(__name__)

BASE_URL = "https://procwise.purpleblock.ai"


@dataclass
class InventoryDiff:
    """Changes between old and new inventory for a single warehouse."""
    warehouse: str
    total_old: int = 0
    total_new: int = 0
    all_items: list[dict] = field(default_factory=list)
    new_items: list[dict] = field(default_factory=list)
    removed_items: list[dict] = field(default_factory=list)
    price_changes: list[dict] = field(default_factory=list)
    stock_changes: list[dict] = field(default_factory=list)


def fetch_current_inventory(
    session: requests.Session,
    warehouse_id: str | None = None,
) -> list[dict]:
    """GET /api/inventory to retrieve current items before upload."""
    headers = {}
    if warehouse_id:
        headers["X-Warehouse-Id"] = warehouse_id
    resp = session.get(f"{BASE_URL}/api/inventory", headers=headers)
    resp.raise_for_status()
    data = resp.json()
    # Response is either a list or {"items": [...], ...} for all-warehouses mode
    if isinstance(data, list):
        return data
    return data.get("items", [])


def compute_diff(
    old_items: list[dict],
    new_items: list[dict],
    warehouse: str,
) -> InventoryDiff:
    """Compare old vs new inventory and return structured diff."""
    diff = InventoryDiff(
        warehouse=warehouse,
        total_old=len(old_items),
        total_new=len(new_items),
        all_items=new_items,
    )

    old_by_ean = {item["ean"]: item for item in old_items}
    new_by_ean = {item["ean"]: item for item in new_items}

    old_eans = set(old_by_ean.keys())
    new_eans = set(new_by_ean.keys())

    # New items (in new but not in old)
    for ean in sorted(new_eans - old_eans):
        item = new_by_ean[ean]
        diff.new_items.append({
            "ean": ean,
            "name": item.get("name", ""),
            "price": item.get("price", 0),
            "stock": item.get("stock", 0),
        })

    # Removed items (in old but not in new)
    for ean in sorted(old_eans - new_eans):
        item = old_by_ean[ean]
        diff.removed_items.append({
            "ean": ean,
            "name": item.get("name", ""),
            "price": item.get("price", 0),
            "stock": item.get("stock", 0),
        })

    # Changed items (in both)
    for ean in sorted(old_eans & new_eans):
        old = old_by_ean[ean]
        new = new_by_ean[ean]

        old_price = int(old.get("price", 0))
        new_price = int(new.get("price", 0))
        if old_price != new_price:
            diff.price_changes.append({
                "ean": ean,
                "name": new.get("name", ""),
                "old_price": old_price,
                "new_price": new_price,
            })

        old_stock = int(old.get("stock", 0))
        new_stock = int(new.get("stock", 0))
        if old_stock != new_stock:
            diff.stock_changes.append({
                "ean": ean,
                "name": new.get("name", ""),
                "old_stock": old_stock,
                "new_stock": new_stock,
            })

    log.info(
        "Diff for %s: %d new, %d removed, %d price changes, %d stock changes",
        warehouse,
        len(diff.new_items),
        len(diff.removed_items),
        len(diff.price_changes),
        len(diff.stock_changes),
    )
    return diff
