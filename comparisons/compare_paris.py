import os
import csv
import math
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass
from difflib import SequenceMatcher

MASTER_FILE = os.path.join(os.environ.get("OUTPUT_DIR", "output"), "catalog.csv")
CATALOG_FILE = os.path.join(os.environ.get("OUTPUT_DIR", "output"), "scrape_paris.csv")
OUTPUT_FILE = os.path.join(os.environ.get("OUTPUT_DIR", "output"), "compare_paris.csv")

STOPWORDS = {
    "PERFUME",
    "BODY",
    "MIST",
    "SPRAY",
    "PARFUM",
    "EDP",
    "EDT",
    "EDC",
    "EAU",
    "DE",
    "TOILETTE",
    "WOMAN",
    "WOMEN",
    "MAN",
    "MEN",
    "HOMBRE",
    "MUJER",
    "UNISEX",
    "ML",
    "SET",
    "ESTUCHE",
    "DESODORANTE",
    "AMBIENTAL",
    "AGUA",
    "FRESCA",
    "THE",
    "AND",
    "FOR",
    "PARA",
    "CON",
    "BY",
    "WITH",
    "NEW",
    "NUEVO",
    "LIMITADA",
    "EDICION",
    "VERSION",
    "LE",
    "LA",
    "EL",
    "LOS",
    "LAS",
    "SIN",
    "TAPA",
    "CAJA",
    "POUR",
    "HER",
    "HIM",
    "EUA",
    "INTENSE",
    "EXTRAIT",
    "EXTRACT",
    "EAUDEPARFUM",
    "EAUDETOILETTE",
    "EAUDECOLOGNE",
    "GEL",
    "DUCHA",
    "TESTER",
}
GENERIC_PRODUCT_TOKENS = {
    "EDITION",
    "LIMITED",
    "LIMITADA",
    "VERSION",
    "NUEVO",
    "NUEVA",
}
BRAND_STOPWORDS = {"AND", "THE", "DE", "LA", "EL", "LE", "PERFUME", "PARFUM"}
MALE_TOKENS = {"HOMBRE", "MEN", "MAN", "HIM"}
FEMALE_TOKENS = {"MUJER", "WOMEN", "WOMAN", "HER", "FEMME"}
SET_TOKENS = {"ESTUCHE", "SET", "GIFTSET"}


@dataclass(frozen=True)
class MasterProduct:
    barcode: str
    price: str
    name: str
    brand: str
    brand_tokens: frozenset[str]
    product_tokens: tuple[str, ...]
    product_token_set: frozenset[str]
    compact_full: str
    compact_core: str
    concentration: frozenset[str]
    sizes_ml: frozenset[int]
    gender: str
    is_tester: bool
    is_set: bool


def normalize_barcode(value) -> str:
    text = "" if value is None else str(value).strip()
    if not text or text.lower() in {"nan", "none", "null"}:
        return ""
    if re.fullmatch(r"\d+\.0+", text):
        return text.split(".", 1)[0]
    return text


def normalize_price(value) -> str:
    text = "" if value is None else str(value).strip()
    if not text:
        return ""

    clean = text.replace(",", "")
    try:
        number = float(clean)
    except ValueError:
        return text

    if number.is_integer():
        return str(int(number))
    return f"{number:.2f}".rstrip("0").rstrip(".")


def normalize_text_ascii(value) -> str:
    text = "" if value is None else str(value)
    text = text.replace("&amp;amp;", "&").replace("&amp;", "&")
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return text.upper()


def compact_text(value) -> str:
    return re.sub(r"[^A-Z0-9]+", "", normalize_text_ascii(value))


def tokenize_text(value) -> list[str]:
    return re.findall(r"[A-Z0-9]+", normalize_text_ascii(value))


def choose_field(fieldnames: list[str], candidates: list[str]) -> str:
    for candidate in candidates:
        if candidate in fieldnames:
            return candidate
    return ""


def is_in_stock(value) -> bool:
    text = "" if value is None else str(value).strip().lower()
    return text.endswith("instock")


def is_strict_numeric_barcode(value: str) -> bool:
    return bool(re.fullmatch(r"\d{5,}", value))


def extract_ml_sizes(value: str) -> set[int]:
    text = normalize_text_ascii(value)
    sizes = {int(num) for num in re.findall(r"(\d{2,4})\s*ML\b", text)}
    for token in tokenize_text(value):
        match = re.fullmatch(r"(\d{2,4})ML", token)
        if match:
            sizes.add(int(match.group(1)))
    return sizes


def detect_gender(tokens: set[str]) -> str:
    if "UNISEX" in tokens:
        return "unisex"

    has_male = bool(tokens & MALE_TOKENS)
    has_female = bool(tokens & FEMALE_TOKENS)
    if has_male and not has_female:
        return "male"
    if has_female and not has_male:
        return "female"
    return "unknown"


def detect_concentration(tokens: set[str], source_text: str) -> set[str]:
    concentration: set[str] = set()
    compact = compact_text(source_text)

    if "EDP" in tokens or "EAUDEPARFUM" in compact:
        concentration.add("EDP")
    if "EDT" in tokens or "EAUDETOILETTE" in compact:
        concentration.add("EDT")
    if "EDC" in tokens or "EAUDECOLOGNE" in compact:
        concentration.add("EDC")
    if "EXTRAIT" in tokens or "EXTRACT" in tokens:
        concentration.add("EXTRACT")
    if "PARFUM" in tokens and "EDP" not in concentration:
        concentration.add("PARFUM")

    return concentration


def detect_is_set(source_text: str) -> bool:
    tokens = set(tokenize_text(source_text))
    return bool(tokens & SET_TOKENS) or "+" in source_text


def normalize_brand_tokens(brand: str) -> tuple[str, ...]:
    output: list[str] = []
    for token in tokenize_text(brand):
        if token in BRAND_STOPWORDS:
            continue
        if token.isdigit() or len(token) <= 1:
            continue
        output.append(token)

    deduped: list[str] = []
    seen: set[str] = set()
    for token in output:
        if token not in seen:
            deduped.append(token)
            seen.add(token)
    return tuple(deduped)


def extract_product_tokens(source_text: str, brand_tokens: set[str]) -> list[str]:
    sizes = extract_ml_sizes(source_text)
    tokens_out: list[str] = []

    for token in tokenize_text(source_text):
        if token in brand_tokens:
            continue
        if token in STOPWORDS or token in GENERIC_PRODUCT_TOKENS:
            continue

        if token.isdigit():
            if int(token) in sizes or len(token) <= 1:
                continue
            tokens_out.append(token)
            continue

        size_match = re.fullmatch(r"(\d{2,4})ML", token)
        if size_match and int(size_match.group(1)) in sizes:
            continue

        if len(token) <= 1:
            continue

        tokens_out.append(token)

    deduped: list[str] = []
    seen: set[str] = set()
    for token in tokens_out:
        if token not in seen:
            deduped.append(token)
            seen.add(token)
    return deduped


def gender_compatible(query_gender: str, candidate_gender: str) -> bool:
    if query_gender == "unknown" or candidate_gender == "unknown":
        return True
    if query_gender == "unisex" or candidate_gender == "unisex":
        return True
    return query_gender == candidate_gender


def load_master_rows(path: str) -> list[MasterProduct]:
    rows: list[MasterProduct] = []
    with open(path, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames or []

        barcode_key = choose_field(fieldnames, ["ean", "Bar Code", "Barcode", "BARCODE", "SKU"])
        price_key = choose_field(fieldnames, ["Price", "price"])
        name_key = choose_field(fieldnames, ["Name", "name", "title", "Product Name", "product_name"])
        brand_key = choose_field(fieldnames, ["Brand", "brand", "Vendor", "vendor"])

        if not barcode_key or not price_key or not name_key:
            raise ValueError(
                f"{path} must include barcode, price, and name columns. Found: {fieldnames}"
            )

        for row in reader:
            barcode = normalize_barcode(row.get(barcode_key))
            if not barcode:
                continue

            name = "" if row.get(name_key) is None else str(row.get(name_key)).strip()
            brand = "" if not brand_key or row.get(brand_key) is None else str(row.get(brand_key)).strip()
            price = normalize_price(row.get(price_key))

            combined_name = f"{brand} {name}".strip()
            all_tokens = set(tokenize_text(combined_name))
            brand_tokens = set(normalize_brand_tokens(brand))
            product_tokens = extract_product_tokens(combined_name, brand_tokens)

            rows.append(
                MasterProduct(
                    barcode=barcode,
                    price=price,
                    name=name,
                    brand=brand,
                    brand_tokens=frozenset(brand_tokens),
                    product_tokens=tuple(product_tokens),
                    product_token_set=frozenset(product_tokens),
                    compact_full=compact_text(combined_name),
                    compact_core=compact_text(" ".join(product_tokens)),
                    concentration=frozenset(detect_concentration(all_tokens, combined_name)),
                    sizes_ml=frozenset(extract_ml_sizes(combined_name)),
                    gender=detect_gender(all_tokens),
                    is_tester="TESTER" in all_tokens,
                    is_set=detect_is_set(combined_name),
                )
            )
    return rows


class NameMatcher:
    def __init__(self, products: list[MasterProduct]):
        self.products = products
        self.brand_token_sequences = self._build_brand_token_sequences(products)
        self.product_token_frequency = Counter[str]()
        for product in products:
            self.product_token_frequency.update(product.product_token_set)

    @staticmethod
    def _build_brand_token_sequences(products: list[MasterProduct]) -> list[tuple[str, ...]]:
        sequences = {
            tuple(product.brand_tokens)
            for product in products
            if product.brand_tokens
        }
        return sorted(
            sequences,
            key=lambda seq: (len(seq), sum(len(token) for token in seq)),
            reverse=True,
        )

    def _detect_query_brand_tokens(self, query_tokens: set[str]) -> set[str]:
        for sequence in self.brand_token_sequences:
            token_set = set(sequence)
            if token_set and token_set.issubset(query_tokens):
                return token_set
        return set()

    def match_product_name(self, query_name: str) -> tuple[str, float]:
        query_name = "" if query_name is None else str(query_name).strip()
        if not query_name:
            return "", 0.0

        query_tokens_all = set(tokenize_text(query_name))
        query_brand_tokens = self._detect_query_brand_tokens(query_tokens_all)
        query_product_tokens = extract_product_tokens(query_name, query_brand_tokens)
        query_product_token_set = set(query_product_tokens)

        if not query_product_token_set:
            return "", 0.0

        query_concentration = detect_concentration(query_tokens_all, query_name)
        query_sizes = extract_ml_sizes(query_name)
        query_gender = detect_gender(query_tokens_all)
        query_is_tester = "TESTER" in query_tokens_all
        query_is_set = detect_is_set(query_name)
        query_compact_core = compact_text(" ".join(query_product_tokens))
        query_compact_full = compact_text(query_name)

        candidates: list[MasterProduct] = []
        for product in self.products:
            if query_brand_tokens and not query_brand_tokens.issubset(product.brand_tokens):
                continue
            if query_concentration and product.concentration and query_concentration.isdisjoint(product.concentration):
                continue
            if query_sizes and product.sizes_ml and query_sizes.isdisjoint(product.sizes_ml):
                continue
            if not gender_compatible(query_gender, product.gender):
                continue
            if query_is_set != product.is_set:
                continue
            candidates.append(product)

        if not candidates:
            return "", 0.0

        high_info_tokens = [
            token
            for token in query_product_token_set
            if len(token) >= 3 and self.product_token_frequency.get(token, 0) <= 5
        ]
        if high_info_tokens:
            candidate_union: set[str] = set()
            for product in candidates:
                candidate_union.update(product.product_token_set)
            if any(token not in candidate_union for token in high_info_tokens):
                return "", 0.0

        query_weight_total = sum(
            1.0 / math.log2(self.product_token_frequency[token] + 2.0)
            for token in query_product_token_set
        )

        scored: list[tuple[float, int, float, bool, MasterProduct]] = []
        for product in candidates:
            shared_tokens = query_product_token_set & product.product_token_set
            weighted_shared = sum(
                1.0 / math.log2(self.product_token_frequency[token] + 2.0)
                for token in shared_tokens
            )
            weighted_coverage = weighted_shared / max(query_weight_total, 1e-9)
            exact_coverage = len(shared_tokens) / len(query_product_token_set)
            union = query_product_token_set | product.product_token_set
            jaccard = len(shared_tokens) / len(union) if union else 0.0

            core_similarity = (
                SequenceMatcher(None, query_compact_core, product.compact_core).ratio()
                if query_compact_core and product.compact_core
                else 0.0
            )
            full_similarity = SequenceMatcher(None, query_compact_full, product.compact_full).ratio()
            brand_ratio = (
                len(query_brand_tokens & product.brand_tokens) / len(query_brand_tokens)
                if query_brand_tokens
                else 0.0
            )

            attribute_score = 0.0
            if query_concentration and product.concentration and not query_concentration.isdisjoint(product.concentration):
                attribute_score += 0.03
            if query_sizes and product.sizes_ml and not query_sizes.isdisjoint(product.sizes_ml):
                attribute_score += 0.03
            if query_gender != "unknown" and product.gender != "unknown" and gender_compatible(query_gender, product.gender):
                attribute_score += 0.02
            if query_is_tester == product.is_tester:
                attribute_score += 0.03
            elif query_is_tester and not product.is_tester:
                attribute_score -= 0.03

            score = (
                0.41 * weighted_coverage
                + 0.16 * exact_coverage
                + 0.12 * jaccard
                + 0.17 * core_similarity
                + 0.08 * full_similarity
                + 0.06 * brand_ratio
                + attribute_score
            )

            scored.append((score, len(shared_tokens), core_similarity, product.is_tester, product))

        if not scored:
            return "", 0.0

        scored.sort(key=lambda item: item[0], reverse=True)
        best_score, best_shared_count, best_core_similarity, best_is_tester, best_product = scored[0]
        second_score = scored[1][0] if len(scored) > 1 else 0.0
        second_is_tester = scored[1][3] if len(scored) > 1 else False
        gap = best_score - second_score

        query_token_count = len(query_product_token_set)
        if query_token_count >= 3:
            min_score, min_gap, min_shared, min_core = 0.72, 0.06, 2, 0.55
        elif query_token_count == 2:
            min_score, min_gap, min_shared, min_core = 0.72, 0.08, 1, 0.55
        else:
            min_score, min_gap, min_shared, min_core = 0.82, 0.10, 1, 0.75

        accepted = (
            best_score >= min_score
            and gap >= min_gap
            and best_shared_count >= min_shared
            and best_core_similarity >= min_core
        )

        if (
            not accepted
            and query_is_tester
            and best_is_tester
            and len(scored) > 1
            and not second_is_tester
            and best_score >= min_score
            and best_shared_count >= min_shared
            and best_core_similarity >= min_core
            and gap >= 0.03
        ):
            accepted = True

        if not accepted:
            return "", 0.0
        return best_product.barcode, best_score


def load_paris_prices(
    path: str,
    matcher: NameMatcher,
    master_barcodes: set[str],
) -> tuple[dict[str, str], dict[str, str], dict[str, int]]:
    price_by_barcode: dict[str, str] = {}
    availability_by_barcode: dict[str, str] = {}
    source_by_barcode: dict[str, str] = {}
    name_score_by_barcode: dict[str, float] = {}

    with open(path, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames or []

        name_key = choose_field(fieldnames, ["name", "Name", "title", "product_name"])
        gtin_key = choose_field(fieldnames, ["gtin_or_equivalent", "GTIN", "barcode", "Bar Code"])
        price_key = choose_field(fieldnames, ["price", "Price", "price_clp"])
        availability_key = choose_field(fieldnames, ["availability", "Availability", "stock"])

        if not name_key or not gtin_key or not price_key or not availability_key:
            raise ValueError(
                f"{path} must include name, gtin_or_equivalent, availability, and price columns. "
                f"Found: {fieldnames}"
            )

        for row in reader:
            in_stock = is_in_stock(row.get(availability_key))
            avail_str = "In Stock" if in_stock else "Out of Stock"

            price = normalize_price(row.get(price_key))
            gtin_or_equivalent = normalize_barcode(row.get(gtin_key))

            if is_strict_numeric_barcode(gtin_or_equivalent):
                if gtin_or_equivalent not in master_barcodes:
                    continue

                existing_in_stock = availability_by_barcode.get(gtin_or_equivalent) == "In Stock"
                if existing_in_stock and not in_stock:
                    continue

                price_by_barcode[gtin_or_equivalent] = price
                availability_by_barcode[gtin_or_equivalent] = avail_str
                source_by_barcode[gtin_or_equivalent] = "barcode"
                continue

            matched_barcode, match_score = matcher.match_product_name(row.get(name_key))
            if not matched_barcode:
                continue
            if source_by_barcode.get(matched_barcode) == "barcode":
                continue

            existing_in_stock = availability_by_barcode.get(matched_barcode) == "In Stock"
            if source_by_barcode.get(matched_barcode) == "name":
                if existing_in_stock and not in_stock:
                    continue
                if existing_in_stock == in_stock:
                    if name_score_by_barcode.get(matched_barcode, -1.0) >= match_score:
                        continue

            price_by_barcode[matched_barcode] = price
            availability_by_barcode[matched_barcode] = avail_str
            source_by_barcode[matched_barcode] = "name"
            name_score_by_barcode[matched_barcode] = match_score

    stats = {
        "barcode_matches": sum(1 for source in source_by_barcode.values() if source == "barcode"),
        "name_matches": sum(1 for source in source_by_barcode.values() if source == "name"),
    }
    return price_by_barcode, availability_by_barcode, stats


def main():
    master_rows = load_master_rows(MASTER_FILE)
    master_barcodes = {row.barcode for row in master_rows}
    matcher = NameMatcher(master_rows)
    paris_prices, paris_availability, stats = load_paris_prices(CATALOG_FILE, matcher, master_barcodes)

    with open(OUTPUT_FILE, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["ean", "Paris Price", "Paris Availability"])
        for row in master_rows:
            writer.writerow([row.barcode, paris_prices.get(row.barcode, ""), paris_availability.get(row.barcode, "")])

    print(
        f"Wrote {OUTPUT_FILE} "
        f"(strict barcode matches: {stats['barcode_matches']}, "
        f"name fallback matches: {stats['name_matches']})"
    )


if __name__ == "__main__":
    main()
