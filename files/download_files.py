#!/usr/bin/env python3
"""Download supplier product files from Chirag's Procwise account and upload them to Kamal's."""

import logging
import os
import re
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()

BASE_URL = "https://procwise.purpleblock.ai"
DOWNLOAD_DIR = Path(os.environ.get("OUTPUT_DIR", Path(__file__).parent)) / "downloads"

SKIP_IF_EXISTS = os.getenv("SKIP_IF_EXISTS", "1").lower() in ("1", "true", "yes")
REPLACE_IF_EXISTS = os.getenv("REPLACE_IF_EXISTS", "0").lower() in ("1", "true", "yes")
if REPLACE_IF_EXISTS:
    SKIP_IF_EXISTS = False

MIME_TYPES = {
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".xls": "application/vnd.ms-excel",
}

TARGET_SUPPLIERS = {
    "Silk Mayorista",
    "Iconic Distribucion",
    "Elite Brands",
    "ElitePerfumes Mayorista",
    "Yauras",
    "Productos de Lujo VIP",
    "Cosmetic Mayorista",
}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
)
log = logging.getLogger(__name__)


def login(session: requests.Session, email: str, password: str) -> None:
    resp = session.post(
        f"{BASE_URL}/api/auth/login",
        json={"email": email, "password": password},
    )
    resp.raise_for_status()
    data = resp.json()
    if not data.get("success"):
        log.error("Login failed: %s", data)
        raise RuntimeError("Login failed")
    user_id = data.get("userId")
    if user_id and not session.cookies.get("userId"):
        session.cookies.set("userId", user_id, domain="procwise.purpleblock.ai", path="/")
    log.info("Logged in as %s (userId: %s)", email, user_id)


def list_files(session: requests.Session) -> list[dict]:
    resp = session.get(f"{BASE_URL}/api/files/list")
    resp.raise_for_status()
    return resp.json()["files"]


def download_file(session: requests.Session, file_info: dict, dest: Path) -> Path:
    file_id = file_info["id"]
    original_name = file_info["originalName"]
    supplier = file_info.get("supplier", "unknown")

    supplier_dir = dest / supplier
    supplier_dir.mkdir(parents=True, exist_ok=True)
    filepath = supplier_dir / original_name

    resp = session.get(f"{BASE_URL}/api/files/download", params={"fileId": file_id}, stream=True)
    resp.raise_for_status()

    with open(filepath, "wb") as f:
        for chunk in resp.iter_content(chunk_size=8192):
            f.write(chunk)

    log.info("Downloaded: %s/%s (%d bytes)", supplier, original_name, file_info["size"])
    return filepath


def _normalize_filename(name: str) -> str:
    return re.sub(r"[\s_\-()]+", "", str(name).strip().lower())


def _matches_existing(filename: str, existing_index: set[str]) -> bool:
    if not filename or not existing_index:
        return False
    base = Path(filename).name
    stem = Path(base).stem
    if _normalize_filename(base) in existing_index:
        return True
    if stem and _normalize_filename(stem) in existing_index:
        return True
    return False


def build_existing_index(files: list[dict]) -> set[str]:
    index: set[str] = set()
    for f in files:
        for key in ("originalName", "name", "filename"):
            val = f.get(key)
            if val:
                base = Path(str(val)).name
                stem = Path(base).stem
                index.add(_normalize_filename(base))
                if stem and stem != base:
                    index.add(_normalize_filename(stem))
    return index


def build_existing_map(files: list[dict]) -> dict[str, list[dict]]:
    mapping: dict[str, list[dict]] = {}
    for f in files:
        for key in ("originalName", "name", "filename"):
            val = f.get(key)
            if val:
                base = Path(str(val)).name
                stem = Path(base).stem
                norm = _normalize_filename(base)
                mapping.setdefault(norm, []).append(f)
                if stem and stem != base:
                    mapping.setdefault(_normalize_filename(stem), []).append(f)
    return mapping


def find_existing_records(filename: str, existing_map: dict[str, list[dict]]) -> list[dict]:
    if not filename or not existing_map:
        return []
    base = Path(filename).name
    stem = Path(base).stem
    matches = list(existing_map.get(_normalize_filename(base), []))
    if stem:
        matches.extend(existing_map.get(_normalize_filename(stem), []))
    seen: set[str] = set()
    unique: list[dict] = []
    for rec in matches:
        rid = rec.get("id")
        if rid and rid in seen:
            continue
        if rid:
            seen.add(rid)
        unique.append(rec)
    return unique


def delete_file(session: requests.Session, file_id: str) -> bool:
    endpoints = [
        ("DELETE", f"{BASE_URL}/api/files/delete", {"fileId": file_id}),
        ("DELETE", f"{BASE_URL}/api/files/{file_id}", None),
        ("POST", f"{BASE_URL}/api/files/delete", {"fileId": file_id}),
    ]
    for method, url, payload in endpoints:
        try:
            if method == "DELETE":
                resp = session.delete(url, json=payload) if payload else session.delete(url)
            else:
                resp = session.post(url, json=payload)
            if resp.status_code in (200, 204):
                try:
                    data = resp.json()
                    if isinstance(data, dict) and data.get("success") is False:
                        continue
                except ValueError:
                    pass
                return True
            if resp.status_code in (404, 405):
                continue
        except Exception as e:
            log.debug("Delete attempt failed: %s", e)
    return False


def delete_existing_records(session: requests.Session, records: list[dict]) -> int:
    deleted = 0
    for rec in records:
        file_id = rec.get("id")
        if not file_id:
            continue
        name = rec.get("originalName") or rec.get("name") or ""
        if delete_file(session, str(file_id)):
            log.info("Deleted existing file: %s (id=%s)", name, file_id)
            deleted += 1
        else:
            log.error("Failed to delete existing file: %s (id=%s)", name, file_id)
    return deleted


def upload_file(session: requests.Session, filepath: Path, region: str, currency: str) -> bool:
    content_type = MIME_TYPES.get(filepath.suffix.lower(), "application/octet-stream")
    headers = {
        "Origin": BASE_URL,
        "Referer": f"{BASE_URL}/files",
    }
    with open(filepath, "rb") as f:
        resp = session.post(
            f"{BASE_URL}/api/files/upload",
            data=[("region", region), ("currency", currency)],
            files={"file": (filepath.name, f, content_type)},
            headers=headers,
        )
    if resp.status_code != 200:
        log.error("Upload failed for %s (status %d): %s", filepath.name, resp.status_code, resp.text)
        return False
    data = resp.json()
    if not data.get("success"):
        log.error("Upload failed for %s: %s", filepath.name, data)
        return False
    log.info("Uploaded: %s (region=%s, currency=%s)", filepath.name, region, currency)
    return True


def main() -> None:
    DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

    # --- Phase 1: Download from Chirag's account ---
    chirag_email = os.getenv("CHIRAG_EMAIL")
    chirag_password = os.getenv("CHIRAG_PASSWORD")
    if not chirag_email or not chirag_password:
        log.error("CHIRAG_EMAIL / CHIRAG_PASSWORD not set in .env")
        raise RuntimeError("CHIRAG_EMAIL / CHIRAG_PASSWORD not set")

    dl_session = requests.Session()
    login(dl_session, chirag_email, chirag_password)

    files = list_files(dl_session)
    log.info("Found %d total files on platform", len(files))

    target_files = [f for f in files if f.get("supplier") in TARGET_SUPPLIERS]
    log.info("Matched %d files for target suppliers", len(target_files))

    if not target_files:
        log.warning("No files matched the target suppliers. Available suppliers: %s",
                     {f.get("supplier") for f in files})
        return

    downloaded: list[tuple[Path, dict]] = []
    for file_info in target_files:
        try:
            filepath = download_file(dl_session, file_info, DOWNLOAD_DIR)
            downloaded.append((filepath, file_info))
        except requests.HTTPError as e:
            log.error("Failed to download %s: %s", file_info["originalName"], e)

    log.info("Downloaded %d files to %s", len(downloaded), DOWNLOAD_DIR)

    # --- Phase 2: Upload to Kamal's account ---
    procwise_email = os.getenv("PROCWISE_EMAIL")
    procwise_password = os.getenv("PROCWISE_PASSWORD")
    if not procwise_email or not procwise_password:
        log.error("PROCWISE_EMAIL / PROCWISE_PASSWORD not set in .env")
        raise RuntimeError("PROCWISE_EMAIL / PROCWISE_PASSWORD not set")

    ul_session = requests.Session()
    login(ul_session, procwise_email, procwise_password)

    # Build existing file index if skip/replace is enabled
    existing_index: set[str] = set()
    existing_map: dict[str, list[dict]] = {}
    if SKIP_IF_EXISTS or REPLACE_IF_EXISTS:
        existing_files = list_files(ul_session)
        existing_index = build_existing_index(existing_files)
        existing_map = build_existing_map(existing_files)
        log.info("Found %d existing files on target account", len(existing_files))

    uploaded = 0
    skipped = 0
    for filepath, file_info in downloaded:
        region = file_info.get("country", "")
        currency = file_info.get("currency", "")

        if REPLACE_IF_EXISTS:
            matches = find_existing_records(filepath.name, existing_map)
            if matches:
                deleted = delete_existing_records(ul_session, matches)
                log.info("Deleted %d existing file(s) for %s", deleted, filepath.name)

        if SKIP_IF_EXISTS and _matches_existing(filepath.name, existing_index):
            log.info("Skipped (already exists): %s", filepath.name)
            skipped += 1
            continue

        if upload_file(ul_session, filepath, region, currency):
            uploaded += 1

    log.info("Done. Downloaded: %d, Uploaded: %d, Skipped: %d", len(downloaded), uploaded, skipped)


if __name__ == "__main__":
    main()
