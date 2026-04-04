import csv
import os

import requests

BASE_URL = os.environ.get("BASE_URL", "https://procwise.purpleblock.ai")
WAREHOUSE_ID = "866d1abb-de61-45f9-b8c6-dc71d82e7501"
OUTPUT_DIR = os.environ.get("OUTPUT_DIR", "output")
OUTPUT_FILE = os.path.join(OUTPUT_DIR, "missing_products.csv")


def main():
    # 1. Log in to get the auth cookie
    session = requests.Session()
    login_resp = session.post(f"{BASE_URL}/api/auth/login", json={
        "email": "kamalmirani@gmail.com",
        "password": "kamal123",
    })
    login_resp.raise_for_status()
    print("Login:", login_resp.json())

    # 2. Call the missing-eans endpoint
    resp = session.get(
        f"{BASE_URL}/api/products/missing-eans",
        headers={"X-Warehouse-Id": WAREHOUSE_ID},
    )
    resp.raise_for_status()

    data = resp.json()
    items = data["items"]
    print(f"Found {len(items)} missing products")

    # 3. Save to CSV
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    with open(OUTPUT_FILE, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["ean", "name"])
        for item in items:
            writer.writerow([item["ean"], item["name"]])

    print(f"Saved {len(items)} products to {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
