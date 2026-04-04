import os
import csv
import re
from collections import defaultdict
from difflib import SequenceMatcher

MASTER_FILE = os.path.join(os.environ.get("OUTPUT_DIR", "output"), "missing_products.csv")
LATTAFA_FILE = os.path.join(os.environ.get("OUTPUT_DIR", "output"), "scrape_lattafa.csv")
OUTPUT_FILE = os.path.join(os.environ.get("OUTPUT_DIR", "output"), "compare_lattafa.csv")

# Chirag name prefixes to strip before comparison
CHIRAG_PREFIXES = [
    "pure concentrated perfume oil",
    "body spray",
    "body mist",
    "ambiental spray",
    "ambiental",
    "desodorante spray",
    "desodorante",
    "estuche",
    "all over spray",
    "pefume",  # typo in data
    "perfume",
    "spray",
]

# Tokens to strip from both sides (noise that doesn't identify the product)
NOISE_SUFFIXES_RE = re.compile(
    r"\s*[-–]\s*$"
    r"|\s*\(.*?\)\s*$"
    r"|\s*[-–]\s+inspirado\s+en\b.*$"
    r"|\s*[-–]\s+parecido\s+a\b.*$"
    r"|\s*[-–]\s+aroma\s+como\b.*$"
    r"|\s*[-–]\s+by\b.*$"
    r"|\s*[-–]\s+nuevo\b.*$"
    r"|\s*[-–]\s+edicion\b.*$"
    r"|\s*[-–]\s+especial\b.*$",
    re.IGNORECASE,
)

# Gender / audience words that don't help matching
GENDER_WORDS = {"mujer", "hombre", "unisex", "women", "men", "for", "her", "him"}

# Format tokens to normalize (edp/edt/ml variations)
FORMAT_RE = re.compile(r"\b(edp|edt|parfum|ml)\b", re.IGNORECASE)

# Spanish product-type words in Lattafa names
LATTAFA_TYPE_WORDS = {
    "desodorante", "ambiental", "corporal", "aceite", "concentrado",
    "perfumed", "collection", "giftset", "set", "pcs",
}


def pick_column(fieldnames, *candidates):
    for candidate in candidates:
        if candidate in fieldnames:
            return candidate
    return None


def collapse_spaces(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def strip_chirag_prefix(name: str) -> str:
    lower = name.lower().strip()
    for prefix in CHIRAG_PREFIXES:
        if lower.startswith(prefix):
            return name[len(prefix):].strip()
    return name


def strip_noise_suffixes(name: str) -> str:
    prev = None
    while prev != name:
        prev = name
        name = NOISE_SUFFIXES_RE.sub("", name).strip()
    return name


def normalize_for_match(value: str) -> str:
    value = value.lower()
    value = value.replace("&amp;amp;", "&").replace("&amp;", "&")
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return collapse_spaces(value)


def clean_name(raw: str) -> str:
    """Full cleaning pipeline: strip prefix, suffix noise, then normalize."""
    name = strip_chirag_prefix(raw)
    name = strip_noise_suffixes(name)
    return normalize_for_match(name)


def get_core_tokens(norm_name: str) -> set:
    """Return tokens minus gender words and pure-number tokens (sizes)."""
    tokens = set(norm_name.split())
    tokens -= GENDER_WORDS
    return tokens


def get_product_tokens(norm_name: str) -> set:
    """Return only product-identifying tokens (no brand, format, gender, numbers)."""
    tokens = set(norm_name.split())
    tokens -= GENDER_WORDS
    tokens -= {"lattafa", "asdaaf", "niche", "emarati", "pride", "rave"}
    tokens -= LATTAFA_TYPE_WORDS
    # Remove pure numbers, format tokens, and pack-size tokens (3pc, 2pcs, etc.)
    tokens = {t for t in tokens if not re.fullmatch(r"\d+|edp|edt|parfum|ml|pcs|\d+pc|\d+pcs", t)}
    return tokens


def detect_product_type(raw_name: str) -> str:
    """Classify a product by its type from the raw name."""
    low = raw_name.lower()
    if re.search(r"\bedp\b|\bedt\b|\beau de\b", low):
        return "fragrance"
    if re.search(r"\bambiental\b|\bair freshener\b", low):
        return "ambiental"
    if re.search(r"\bdesodorante\b|\bdeo\b|\bperfumed spray\b", low):
        return "deodorant"
    if re.search(r"\ball over spray\b|\bbody spray\b|\bbody mist\b", low):
        return "body_spray"
    if re.search(r"\baceite\b|\boil\b", low):
        return "oil"
    if re.search(r"\bestuche\b|\bgiftset\b|\bset\b.*\bpcs\b", low):
        return "set"
    return "unknown"


def types_compatible(type_a: str, type_b: str) -> bool:
    """Check if two product types are compatible for matching."""
    if type_a == type_b:
        return True
    if "unknown" in (type_a, type_b):
        return True
    return False


def fuzzy_token_match(token: str, candidates: set, threshold: float = 0.8) -> bool:
    """Check if token has a close match in candidates (handles typos)."""
    if token in candidates:
        return True
    for cand in candidates:
        if SequenceMatcher(None, token, cand).ratio() >= threshold:
            return True
    return False


def all_tokens_fuzzy_matched(source_tokens: set, target_tokens: set) -> bool:
    """Check that every token in source has a fuzzy match in target."""
    for token in source_tokens:
        if not fuzzy_token_match(token, target_tokens):
            return False
    return True


def is_all_digits(value: str) -> bool:
    return bool(value) and value.isdigit()


def load_lattafa_entries(path: str):
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames or []

        name_key = pick_column(fieldnames, "name", "Name")
        price_key = pick_column(fieldnames, "price_clp", "Price", "price")
        gtin_key = pick_column(fieldnames, "gtin_or_equivalent", "GTIN", "barcode")
        if not name_key or not price_key:
            raise ValueError(
                f"{path} must include name and price columns. Found: {fieldnames}"
            )

        entries = []
        for idx, row in enumerate(reader):
            raw_name = str(row.get(name_key, "") or "")
            raw_price = str(row.get(price_key, "") or "").strip()
            gtin = str(row.get(gtin_key, "") or "").strip() if gtin_key else ""
            cleaned = clean_name(raw_name)
            core_tokens = get_core_tokens(cleaned)
            product_tokens = get_product_tokens(cleaned)
            ptype = detect_product_type(raw_name)
            entries.append(
                {
                    "idx": idx,
                    "raw_name": collapse_spaces(raw_name),
                    "price": raw_price,
                    "gtin": gtin,
                    "cleaned": cleaned,
                    "core_tokens": core_tokens,
                    "product_tokens": product_tokens,
                    "ptype": ptype,
                }
            )

    return entries


def load_master_rows(path: str):
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames or []
        name_key = pick_column(fieldnames, "Name", "name", "title")
        barcode_key = pick_column(fieldnames, "ean", "Bar Code", "barcode", "Barcode")
        if not name_key:
            raise ValueError(
                f"{path} must include a Name column. Found: {fieldnames}"
            )

        rows = []
        for idx, row in enumerate(reader):
            name = str(row.get(name_key, "") or "")
            barcode = str(row.get(barcode_key, "") or "").strip() if barcode_key else ""
            cleaned = clean_name(name)
            core_tokens = get_core_tokens(cleaned)
            product_tokens = get_product_tokens(cleaned)
            ptype = detect_product_type(name)
            rows.append(
                {
                    "idx": idx,
                    "row": row,
                    "name": name,
                    "barcode": barcode,
                    "cleaned": cleaned,
                    "core_tokens": core_tokens,
                    "product_tokens": product_tokens,
                    "ptype": ptype,
                }
            )

    return fieldnames, rows


def match_by_barcode(lattafa_entries, master_rows):
    """Exact barcode matching for entries with all-digit GTINs."""
    barcode_to_master = {}
    for m in master_rows:
        bc = m["barcode"]
        if bc:
            barcode_to_master[bc] = m["idx"]

    matches = {}  # master_idx -> lattafa_idx
    matched_lattafa = set()
    matched_master = set()

    for lat in lattafa_entries:
        if not is_all_digits(lat["gtin"]):
            continue
        master_idx = barcode_to_master.get(lat["gtin"])
        if master_idx is not None and master_idx not in matched_master:
            matches[master_idx] = lat["idx"]
            matched_lattafa.add(lat["idx"])
            matched_master.add(master_idx)

    return matches, matched_lattafa, matched_master


def build_token_index(master_rows, exclude_idxs):
    """Inverted index: token -> set of master indices."""
    index = defaultdict(set)
    for m in master_rows:
        if m["idx"] in exclude_idxs:
            continue
        for token in m["product_tokens"]:
            index[token].add(m["idx"])
    return index


def find_name_candidates(lattafa_entries, master_rows, token_index,
                         skip_lattafa, skip_master):
    """Find candidate pairs using the inverted token index."""
    master_by_idx = {m["idx"]: m for m in master_rows}
    candidates = []

    for lat in lattafa_entries:
        if lat["idx"] in skip_lattafa:
            continue

        lat_prod = lat["product_tokens"]
        if not lat_prod:
            continue

        hit_count = defaultdict(int)
        for token in lat_prod:
            for master_idx in token_index.get(token, set()):
                hit_count[master_idx] += 1
        candidate_idxs = {idx for idx, count in hit_count.items() if count >= 2}

        candidate_idxs -= skip_master

        for master_idx in candidate_idxs:
            m = master_by_idx[master_idx]

            if not types_compatible(lat["ptype"], m["ptype"]):
                continue

            m_prod = m["product_tokens"]
            if lat_prod and m_prod:
                prod_shared = lat_prod & m_prod
                prod_overlap = len(prod_shared) / max(len(lat_prod), len(m_prod))
            else:
                prod_overlap = 0.0

            if prod_overlap < 0.65:
                continue

            unmatched_lat = lat_prod - prod_shared
            if unmatched_lat and not all_tokens_fuzzy_matched(unmatched_lat, m_prod):
                continue

            lat_core = lat["core_tokens"]
            m_core = m["core_tokens"]
            if not lat_core:
                continue

            shared = lat_core & m_core
            core_overlap = len(shared) / max(len(lat_core), len(m_core))

            length_gap = abs(len(m["cleaned"]) - len(lat["cleaned"]))

            score = (prod_overlap, core_overlap, -length_gap)
            candidates.append(
                {
                    "score": score,
                    "lat_idx": lat["idx"],
                    "master_idx": master_idx,
                }
            )

    return candidates


def choose_one_to_one_matches(candidates):
    sorted_candidates = sorted(
        candidates,
        key=lambda c: (
            c["score"][0],
            c["score"][1],
            c["score"][2],
            -c["lat_idx"],
            -c["master_idx"],
        ),
        reverse=True,
    )

    used_lattafa = set()
    used_master = set()
    selected = {}

    for cand in sorted_candidates:
        lat_idx = cand["lat_idx"]
        master_idx = cand["master_idx"]
        if lat_idx in used_lattafa or master_idx in used_master:
            continue

        used_lattafa.add(lat_idx)
        used_master.add(master_idx)
        selected[master_idx] = lat_idx

    return selected, used_lattafa, used_master


def main():
    lattafa_entries = load_lattafa_entries(LATTAFA_FILE)
    fieldnames, master_rows = load_master_rows(MASTER_FILE)

    # Phase 1: exact barcode matches
    bc_matches, bc_used_lat, bc_used_master = match_by_barcode(
        lattafa_entries, master_rows
    )
    print(f"Phase 1 — Barcode matches: {len(bc_matches)}")

    # Phase 2: name-based matching for remaining entries
    token_index = build_token_index(master_rows, bc_used_master)
    name_candidates = find_name_candidates(
        lattafa_entries, master_rows, token_index, bc_used_lat, bc_used_master
    )
    name_matches, name_used_lat, name_used_master = choose_one_to_one_matches(
        name_candidates
    )
    print(f"Phase 2 — Name matches: {len(name_matches)}")

    # Merge both phases
    all_matches = {**bc_matches, **name_matches}
    all_used_lat = bc_used_lat | name_used_lat
    all_used_master = bc_used_master | name_used_master

    with open(OUTPUT_FILE, "w", encoding="utf-8", newline="") as dst:
        writer = csv.writer(dst)
        writer.writerow(["ean", "Lattafa Price", "Lattafa Availability"])

        for m in master_rows:
            lat_idx = all_matches.get(m["idx"])
            if lat_idx is None:
                writer.writerow([m["barcode"], "", ""])
            else:
                writer.writerow([m["barcode"], lattafa_entries[lat_idx]["price"], "In Stock"])

    print(f"\nDone. Wrote {len(master_rows)} rows to {OUTPUT_FILE}.")
    print(
        f"Total Lattafa entries matched: "
        f"{len(all_used_lat)}/{len(lattafa_entries)}"
    )
    print(f"Total master rows matched: {len(all_used_master)}/{len(master_rows)}")


if __name__ == "__main__":
    main()
