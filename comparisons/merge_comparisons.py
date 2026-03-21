import csv
import os

CATALOG_FILE = os.path.join(os.environ.get("OUTPUT_DIR", "output"), "catalog.csv")
OUTPUT_FILE = os.path.join(os.environ.get("OUTPUT_DIR", "output"), "merged_comparisons.csv")

# (display name, compare csv file, price column, availability column)
COMPETITORS = [
    ("Cosmetic", os.path.join(os.environ.get("OUTPUT_DIR", "output"), "compare_cosmetic.csv"), "Cosmetic Price", "Cosmetic Availability"),
    ("Elite Perfumes", os.path.join(os.environ.get("OUTPUT_DIR", "output"), "compare_elite.csv"), "Elite Perfumes Price", "Elite Perfumes Availability"),
    ("Lodoro", os.path.join(os.environ.get("OUTPUT_DIR", "output"), "compare_lodoro.csv"), "Lodoro Price", "Lodoro Availability"),
    ("Multimarcas Perfumes", os.path.join(os.environ.get("OUTPUT_DIR", "output"), "compare_multimarcas.csv"), "Multimarcas Perfumes Price", "Multimarcas Perfumes Availability"),
    ("Productos de Lujo", os.path.join(os.environ.get("OUTPUT_DIR", "output"), "compare_productos.csv"), "Productos de Lujo Price", "Productos de Lujo Availability"),
    ("Yauras", os.path.join(os.environ.get("OUTPUT_DIR", "output"), "compare_yauras.csv"), "Yauras Price", "Yauras Availability"),
    ("Paris", os.path.join(os.environ.get("OUTPUT_DIR", "output"), "compare_paris.csv"), "Paris Price", "Paris Availability"),
    ("Sairam", os.path.join(os.environ.get("OUTPUT_DIR", "output"), "compare_sairam.csv"), "Sairam Price", "Sairam Availability"),
    ("Lattafa", os.path.join(os.environ.get("OUTPUT_DIR", "output"), "compare_lattafa.csv"), "Lattafa Price", "Lattafa Availability"),
]


def parse_price(value):
    if value is None:
        return None
    text = str(value).strip().replace(",", "")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def load_catalog(path):
    catalog = {}
    with open(path, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            ean = str(row.get("ean", "")).strip()
            if not ean:
                continue
            catalog[ean] = {
                "name": str(row.get("name", "") or "").strip(),
                "brand": str(row.get("brand", "") or "").strip(),
                "stock": str(row.get("stock", "") or "").strip(),
                "price": str(row.get("price", "") or "").strip(),
            }
    return catalog


def load_competitor(file_path, price_col, avail_col):
    """Returns dict: ean -> (price_str, availability_str)"""
    data = {}
    if not os.path.exists(file_path):
        print(f"  WARNING: {file_path} not found, skipping.")
        return data
    with open(file_path, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            ean = str(row.get("ean", "")).strip()
            if not ean:
                continue
            price = str(row.get(price_col, "") or "").strip()
            avail = str(row.get(avail_col, "") or "").strip()
            data[ean] = (price, avail)
    return data


def compute_cheapest_and_gap(my_price, competitor_prices):
    """
    my_price: float or None
    competitor_prices: list of (name, float_price) — only in-stock competitors

    Returns (price_gap_str, cheapest_price_display, cheapest_site_str)
    """
    candidates = []
    if my_price is not None:
        candidates.append(("My Website", my_price))
    candidates.extend(competitor_prices)

    if not candidates:
        return ("", "", "")

    least_price = min(p for _, p in candidates)
    least_names = ", ".join(
        sorted(name for name, p in candidates if p == least_price)
    )
    least_price_display = (
        str(int(least_price)) if least_price == int(least_price) else f"{least_price:.2f}"
    )

    if my_price is None:
        price_gap = ""
    elif least_names == "My Website":
        competitor_only = [p for name, p in candidates if name != "My Website"]
        if competitor_only:
            second_least = min(competitor_only)
            price_gap = f"{((my_price - second_least) / second_least * 100):.2f}%"
        else:
            price_gap = "0.00%"
    else:
        price_gap = f"{((my_price - least_price) / least_price * 100):.2f}%"

    return (price_gap, least_price_display, least_names)


def main():
    print("Loading catalog...")
    catalog = load_catalog(CATALOG_FILE)
    print(f"  {len(catalog)} products loaded.")

    print("Loading competitor comparisons...")
    competitor_data = {}
    for display_name, file_path, price_col, avail_col in COMPETITORS:
        print(f"  Loading {display_name}...")
        competitor_data[display_name] = load_competitor(file_path, price_col, avail_col)

    competitor_names = [c[0] for c in COMPETITORS]
    header = [
        "Bar Code", "Name", "Brand", "Stock", "My Price",
        "Cheapest Price", "Cheapest Site", "Price Gap %",
    ] + competitor_names

    print(f"Writing {OUTPUT_FILE}...")
    with open(OUTPUT_FILE, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(header)

        for ean, info in catalog.items():
            my_price = parse_price(info["price"])

            in_stock_prices = []
            competitor_cells = []

            for name in competitor_names:
                price_str, avail = competitor_data[name].get(ean, ("", ""))
                comp_price = parse_price(price_str)

                is_in_stock = avail.strip().lower() == "in stock"

                if comp_price is not None and is_in_stock:
                    cell = str(int(comp_price)) if comp_price == int(comp_price) else f"{comp_price:.2f}"
                    competitor_cells.append(cell)
                    in_stock_prices.append((name, comp_price))
                else:
                    competitor_cells.append("")

            price_gap, cheapest_price, cheapest_site = compute_cheapest_and_gap(
                my_price, in_stock_prices
            )

            row = [
                ean,
                info["name"],
                info["brand"],
                info["stock"],
                info["price"],
                cheapest_price,
                cheapest_site,
                price_gap,
            ] + competitor_cells

            writer.writerow(row)

    print(f"Done. Wrote {len(catalog)} rows to {OUTPUT_FILE}.")


if __name__ == "__main__":
    main()
