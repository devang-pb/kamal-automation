#!/usr/bin/env python3
"""AWS Lambda handler — comparison pipeline with three modes.

  mode="full" (default):
    Dispatch phase — runs 3 scrapers locally, fires 6 Shopify worker
    Lambdas async (1 store each), uploads scraper results to S3.
    Completes in ~5 minutes.

  mode="shopify_worker":
    Worker — runs the specified Shopify compare and uploads the result
    CSV to S3. Each worker gets its own 900s budget.

  mode="merge":
    Merge phase — downloads all comparison CSVs from S3, runs fuzzy
    matchers, merges everything, uploads to ProcWise + S3.
    Triggered by EventBridge ~15 min after dispatch.
    Completes in ~60 seconds.
"""

import json
import logging
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed

OUTPUT_DIR = "/tmp/output"
os.environ["OUTPUT_DIR"] = OUTPUT_DIR
os.environ["COMPARE_MAX_WORKERS"] = "3"  # Threads per compare script (low to avoid 429s)
os.makedirs(OUTPUT_DIR, exist_ok=True)

# Configure logging for CloudWatch
root = logging.getLogger()
root.setLevel(logging.INFO)
if root.handlers:
    for h in root.handlers:
        h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S"))
logger = logging.getLogger(__name__)

S3_BUCKET = os.environ.get("S3_BUCKET", "kamal-automation-data")
FUNCTION_NAME = os.environ.get("AWS_LAMBDA_FUNCTION_NAME", "kamal-comparison-pipeline")

SHOPIFY_STORES = [
    "cosmetic", "elite", "lodoro",
    "multimarcas", "productos", "yauras",
]


def run_script(name, func):
    """Run a script function and return (name, success, error)."""
    try:
        logger.info("Starting %s", name)
        func()
        logger.info("Completed %s", name)
        return (name, True, None)
    except Exception as e:
        logger.error("Failed %s: %s", name, e)
        return (name, False, str(e))


def _import_compare(store):
    """Dynamically import a compare_<store> module and return its main()."""
    mod = __import__(f"compare_{store}")
    return mod.main


def handler(event, context):
    """Lambda entry point — dispatches based on mode."""
    mode = event.get("mode", "full")
    if mode == "shopify_worker":
        return _shopify_worker(event)
    if mode == "merge":
        return _merge_phase(event)
    return _dispatch_phase(event, context)


# ---------------------------------------------------------------------------
# Mode: shopify_worker
# ---------------------------------------------------------------------------

def _shopify_worker(event):
    """Worker mode: run specified Shopify compares sequentially, upload to S3."""
    try:
        import boto3
        s3 = boto3.client("s3")
        stores = event.get("stores", [])
        # Allow per-worker concurrency override for rate-limited sites
        worker_threads = event.get("max_workers")
        if worker_threads:
            os.environ["COMPARE_MAX_WORKERS"] = str(worker_threads)
        logger.info("Worker starting: stores=%s, threads=%s", stores, os.environ.get("COMPARE_MAX_WORKERS"))

        # Download catalog
        catalog_path = f"{OUTPUT_DIR}/catalog.csv"
        s3.download_file(S3_BUCKET, "catalog.csv", catalog_path)
        logger.info("Downloaded catalog.csv (%d bytes)", os.path.getsize(catalog_path))

        # Run each store compare sequentially (avoids 429s)
        results = []
        for store in stores:
            func = _import_compare(store)
            results.append(run_script(f"compare_{store}", func))

        # Upload result CSVs to S3
        for store in stores:
            filename = f"compare_{store}.csv"
            filepath = f"{OUTPUT_DIR}/{filename}"
            if os.path.exists(filepath):
                s3.upload_file(filepath, S3_BUCKET, f"comparisons/{filename}")
                logger.info("Uploaded %s to S3", filename)

        failures = [n for n, ok, _ in results if not ok]
        return {
            "statusCode": 200,
            "body": json.dumps({"stores": stores, "failures": failures}),
        }

    except (Exception, SystemExit) as e:
        logger.exception("Worker failed")
        return {
            "statusCode": 500,
            "body": json.dumps({"error": str(e)}),
        }


# ---------------------------------------------------------------------------
# Mode: full (dispatch phase)
# ---------------------------------------------------------------------------

def _fire_async_worker(lambda_client, stores, max_workers=None):
    """Fire a worker Lambda asynchronously (Event invocation)."""
    payload = {"mode": "shopify_worker", "stores": stores}
    if max_workers:
        payload["max_workers"] = max_workers
    logger.info("Firing async worker: stores=%s, threads=%s", stores, max_workers or "default")
    lambda_client.invoke(
        FunctionName=FUNCTION_NAME,
        InvocationType="Event",
        Payload=json.dumps(payload),
    )


def _dispatch_phase(event, context):
    """Dispatch phase: fire async workers + run scrapers + upload to S3."""
    try:
        import boto3

        s3 = boto3.client("s3")
        lambda_client = boto3.client("lambda")

        # Step 1: Download catalog.csv from S3
        logger.info("=== Step 1: Download catalog.csv from S3 ===")
        catalog_path = f"{OUTPUT_DIR}/catalog.csv"
        s3.download_file(S3_BUCKET, "catalog.csv", catalog_path)
        logger.info("Downloaded catalog.csv (%d bytes)", os.path.getsize(catalog_path))

        # Step 2: Fire 6 Shopify workers async (each gets its own 900s)
        logger.info("=== Step 2: Fire 6 async Shopify workers ===")
        _fire_async_worker(lambda_client, ["cosmetic"])
        _fire_async_worker(lambda_client, ["elite"])
        _fire_async_worker(lambda_client, ["lodoro"], max_workers=2)
        _fire_async_worker(lambda_client, ["multimarcas"])
        _fire_async_worker(lambda_client, ["productos"], max_workers=2)
        _fire_async_worker(lambda_client, ["yauras"], max_workers=2)
        logger.info("All 6 workers fired")

        # Step 3: Run scrapers locally in parallel
        logger.info("=== Step 3: Run scrapers ===")
        from scrape_sairam import run as sairam_scrape
        from scrape_paris import run as paris_scrape
        from scrape_lattafa import run as lattafa_scrape

        scraper_results = []
        with ThreadPoolExecutor(max_workers=3) as executor:
            futures = {
                executor.submit(run_script, "scrape_sairam", sairam_scrape): "scrape_sairam",
                executor.submit(run_script, "scrape_paris", paris_scrape): "scrape_paris",
                executor.submit(run_script, "scrape_lattafa", lattafa_scrape): "scrape_lattafa",
            }
            for future in as_completed(futures):
                name = futures[future]
                try:
                    scraper_results.append(future.result())
                except Exception as e:
                    logger.error("Scraper %s raised: %s", name, e)
                    scraper_results.append((name, False, str(e)))

        # Step 4: Upload scraper results to S3
        logger.info("=== Step 4: Upload scraper results to S3 ===")
        for filename in os.listdir(OUTPUT_DIR):
            if filename.startswith("scrape_") and filename.endswith(".csv"):
                filepath = f"{OUTPUT_DIR}/{filename}"
                s3.upload_file(filepath, S3_BUCKET, f"comparisons/{filename}")
                logger.info("Uploaded %s", filename)

        failures = [(n, e) for n, ok, e in scraper_results if not ok]
        summary = {
            "phase": "dispatch",
            "scrapers_completed": len([r for r in scraper_results if r[1]]),
            "scrapers_failed": len(failures),
            "failures": [name for name, _ in failures],
            "workers_fired": 6,
        }
        logger.info("Dispatch complete: %s", json.dumps(summary))
        return {
            "statusCode": 200,
            "body": json.dumps(summary),
        }

    except (Exception, SystemExit) as e:
        logger.exception("Dispatch failed")
        return {
            "statusCode": 500,
            "body": json.dumps({"error": str(e)}),
        }


# ---------------------------------------------------------------------------
# Mode: merge
# ---------------------------------------------------------------------------

def _merge_phase(event):
    """Merge phase: download all CSVs from S3, fuzzy match, merge, upload."""
    try:
        import boto3

        s3 = boto3.client("s3")

        # Step 1: Download catalog
        logger.info("=== Merge Step 1: Download catalog ===")
        catalog_path = f"{OUTPUT_DIR}/catalog.csv"
        s3.download_file(S3_BUCKET, "catalog.csv", catalog_path)
        logger.info("Downloaded catalog.csv (%d bytes)", os.path.getsize(catalog_path))

        # Step 2: Download all comparison CSVs from S3
        logger.info("=== Merge Step 2: Download comparison CSVs ===")
        all_files = ["compare_cosmetic", "compare_elite", "compare_lodoro",
                      "compare_multimarcas", "compare_productos", "compare_yauras",
                      "scrape_sairam", "scrape_paris", "scrape_lattafa"]
        downloaded = []
        for name in all_files:
            filename = f"{name}.csv"
            local_path = f"{OUTPUT_DIR}/{filename}"
            try:
                s3.download_file(S3_BUCKET, f"comparisons/{filename}", local_path)
                size = os.path.getsize(local_path)
                logger.info("Downloaded %s (%d bytes)", filename, size)
                downloaded.append(name)
            except Exception as e:
                logger.error("Failed to download %s: %s", filename, e)

        logger.info("Downloaded %d/%d files", len(downloaded), len(all_files))

        # Step 3: Run fuzzy matchers (sairam, paris, lattafa)
        logger.info("=== Merge Step 3: Fuzzy matchers ===")
        from compare_sairam import main as sairam_compare
        from compare_paris import main as paris_compare
        from compare_lattafa import main as lattafa_compare

        results = []
        for name, func in [
            ("compare_sairam", sairam_compare),
            ("compare_paris", paris_compare),
            ("compare_lattafa", lattafa_compare),
        ]:
            results.append(run_script(name, func))

        # Step 4: Merge all comparisons
        logger.info("=== Merge Step 4: Merge comparisons ===")
        from merge_comparisons import main as merge_main
        merge_main()

        # Step 5: Upload to ProcWise
        logger.info("=== Merge Step 5: Upload to ProcWise ===")
        try:
            from upload_retail_intel import main as upload_retail_intel_main
            upload_retail_intel_main()
            logger.info("ProcWise upload completed")
        except Exception as e:
            logger.error("ProcWise upload failed: %s", e, exc_info=True)

        # Step 6: Upload final results to S3
        logger.info("=== Merge Step 6: Upload results to S3 ===")
        for filename in os.listdir(OUTPUT_DIR):
            if filename.endswith(".csv") and filename != "catalog.csv":
                filepath = f"{OUTPUT_DIR}/{filename}"
                s3.upload_file(filepath, S3_BUCKET, f"comparisons/{filename}")
                logger.info("Uploaded %s", filename)

        failures = [(n, e) for n, ok, e in results if not ok]

        # Step 7: Send email report with full comparison data
        logger.info("=== Merge Step 7: Sending email report ===")
        try:
            from send_comparison_report import send_comparison_report
            send_comparison_report(failures)
        except Exception as e:
            logger.error("Failed to send comparison report: %s", e, exc_info=True)
        summary = {
            "phase": "merge",
            "files_downloaded": len(downloaded),
            "fuzzy_completed": len([r for r in results if r[1]]),
            "fuzzy_failed": len(failures),
            "failures": [name for name, _ in failures],
        }
        logger.info("Merge complete: %s", json.dumps(summary))
        return {
            "statusCode": 200,
            "body": json.dumps(summary),
        }

    except (Exception, SystemExit) as e:
        logger.exception("Merge failed")
        return {
            "statusCode": 500,
            "body": json.dumps({"error": str(e)}),
        }
