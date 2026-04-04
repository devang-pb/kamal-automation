import csv
import os

OUTPUT_DIR = os.environ.get("OUTPUT_DIR", "output")
MASTER_FILE = os.path.join(OUTPUT_DIR, "missing_products.csv")
OUTPUT_FILE = os.path.join(OUTPUT_DIR, "extra_merged_comparisons.csv")

# (column header, compare csv file, price column, availability column)
COMPETITORS = [
    ("cosmetic", os.path.join(OUTPUT_DIR, "compare_cosmetic.csv"), "Cosmetic Price", "Cosmetic Availability"),
    ("productos", os.path.join(OUTPUT_DIR, "compare_productos.csv"), "Productos de Lujo Price", "Productos de Lujo Availability"),
    ("lodoro", os.path.join(OUTPUT_DIR, "compare_lodoro.csv"), "Lodoro Price", "Lodoro Availability"),
    ("elite", os.path.join(OUTPUT_DIR, "compare_elite.csv"), "Elite Perfumes Price", "Elite Perfumes Availability"),
    ("multimarcas", os.path.join(OUTPUT_DIR, "compare_multimarcas.csv"), "Multimarcas Perfumes Price", "Multimarcas Perfumes Availability"),
    ("yauras", os.path.join(OUTPUT_DIR, "compare_yauras.csv"), "Yauras Price", "Yauras Availability"),
    ("sairam", os.path.join(OUTPUT_DIR, "compare_sairam.csv"), "Sairam Price", "Sairam Availability"),
    ("paris", os.path.join(OUTPUT_DIR, "compare_paris.csv"), "Paris Price", "Paris Availability"),
    ("lattafa", os.path.join(OUTPUT_DIR, "compare_lattafa.csv"), "Lattafa Price", "Lattafa Availability"),
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


def load_master(path):
    products = []
    with open(path, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            ean = str(row.get("ean", "")).strip()
            if not ean:
                continue
            name = str(row.get("name", "") or "").strip()
            products.append({"ean": ean, "name": name})
    return products


def load_competitor(file_path, price_col, avail_col):
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


def main():
    print("Loading missing products...")
    products = load_master(MASTER_FILE)
    print(f"  {len(products)} products loaded.")

    print("Loading competitor comparisons...")
    competitor_data = {}
    for col_name, file_path, price_col, avail_col in COMPETITORS:
        print(f"  Loading {col_name}...")
        competitor_data[col_name] = load_competitor(file_path, price_col, avail_col)

    header = ["name", "ean"] + [c[0] for c in COMPETITORS]

    print(f"Writing {OUTPUT_FILE}...")
    with open(OUTPUT_FILE, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(header)

        for product in products:
            ean = product["ean"]
            row = [product["name"], ean]

            for col_name, _, _, _ in COMPETITORS:
                price_str, avail = competitor_data[col_name].get(ean, ("", ""))
                comp_price = parse_price(price_str)
                is_in_stock = avail.strip().lower() == "in stock"

                if comp_price is not None and is_in_stock:
                    cell = str(int(comp_price)) if comp_price == int(comp_price) else f"{comp_price:.2f}"
                    row.append(cell)
                else:
                    row.append("")

            writer.writerow(row)

    print(f"Done. Wrote {len(products)} rows to {OUTPUT_FILE}.")


if __name__ == "__main__":
    main()
