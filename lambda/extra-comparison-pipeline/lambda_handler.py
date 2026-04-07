#!/usr/bin/env python3
"""AWS Lambda handler — extra comparison pipeline.

Runs comparisons for products missing from the main catalog using the
scripts in extra-comparisons/.

Pipeline:
  1. get_missing_products  → missing_products.csv
  2. 6 Shopify compares    (use missing_products.csv, run as async workers)
  3. Download scrape_*.csv from S3 (produced by the main comparison pipeline)
  4. 3 fuzzy matchers      (sairam, paris, lattafa — use scrape_*.csv)
  5. merge_comparisons     → extra_merged_comparisons.csv
  6. Upload results to S3
  7. upload_missing_products → POST to ProcWise /api/retail-intel/missing-products

Supports three modes:
  mode="full"  (default) — runs get_missing_products, fires 6 Shopify workers,
                            then returns. Merge runs later via EventBridge.
  mode="shopify_worker"  — worker: runs specified Shopify compares, uploads to S3.
  mode="merge"           — downloads all CSVs, runs fuzzy matchers, merges, uploads.
"""

import json
import logging
import os
import sys

OUTPUT_DIR = "/tmp/output"
os.environ["OUTPUT_DIR"] = OUTPUT_DIR
os.environ["COMPARE_MAX_WORKERS"] = "3"
os.makedirs(OUTPUT_DIR, exist_ok=True)

root = logging.getLogger()
root.setLevel(logging.INFO)
if root.handlers:
    for h in root.handlers:
        h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S"))
logger = logging.getLogger(__name__)

S3_BUCKET = os.environ.get("S3_BUCKET", "kamal-automation-data")
S3_PREFIX = "extra-comparisons"
FUNCTION_NAME = os.environ.get("AWS_LAMBDA_FUNCTION_NAME", "kamal-extra-comparison-pipeline")

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
        worker_threads = event.get("max_workers")
        if worker_threads:
            os.environ["COMPARE_MAX_WORKERS"] = str(worker_threads)
        logger.info("Worker starting: stores=%s, threads=%s", stores, os.environ.get("COMPARE_MAX_WORKERS"))

        # Download missing_products.csv
        missing_path = f"{OUTPUT_DIR}/missing_products.csv"
        s3.download_file(S3_BUCKET, f"{S3_PREFIX}/missing_products.csv", missing_path)
        logger.info("Downloaded missing_products.csv (%d bytes)", os.path.getsize(missing_path))

        # Run each store compare sequentially
        results = []
        for store in stores:
            func = _import_compare(store)
            results.append(run_script(f"compare_{store}", func))

        # Upload result CSVs to S3
        for store in stores:
            filename = f"compare_{store}.csv"
            filepath = f"{OUTPUT_DIR}/{filename}"
            if os.path.exists(filepath):
                s3.upload_file(filepath, S3_BUCKET, f"{S3_PREFIX}/{filename}")
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
    """Dispatch phase: get missing products, fire Shopify workers, upload to S3."""
    try:
        import boto3

        s3 = boto3.client("s3")
        lambda_client = boto3.client("lambda")

        # Step 1: Run get_missing_products to generate missing_products.csv
        logger.info("=== Step 1: get_missing_products ===")
        from get_missing_products import main as get_missing_main
        get_missing_main()

        missing_path = f"{OUTPUT_DIR}/missing_products.csv"
        if not os.path.exists(missing_path):
            raise FileNotFoundError("missing_products.csv was not generated")
        logger.info("missing_products.csv generated (%d bytes)", os.path.getsize(missing_path))

        # Upload missing_products.csv to S3 so workers can access it
        s3.upload_file(missing_path, S3_BUCKET, f"{S3_PREFIX}/missing_products.csv")
        logger.info("Uploaded missing_products.csv to S3")

        # Step 2: Fire 6 Shopify workers async
        logger.info("=== Step 2: Fire 6 async Shopify workers ===")
        _fire_async_worker(lambda_client, ["cosmetic"])
        _fire_async_worker(lambda_client, ["elite"])
        _fire_async_worker(lambda_client, ["lodoro"], max_workers=2)
        _fire_async_worker(lambda_client, ["multimarcas"])
        _fire_async_worker(lambda_client, ["productos"], max_workers=2)
        _fire_async_worker(lambda_client, ["yauras"], max_workers=2)
        logger.info("All 6 workers fired")

        summary = {
            "phase": "dispatch",
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
    """Merge phase: download CSVs, run fuzzy matchers, merge, upload."""
    try:
        import boto3

        s3 = boto3.client("s3")

        # Step 1: Download missing_products.csv
        logger.info("=== Merge Step 1: Download missing_products.csv ===")
        missing_path = f"{OUTPUT_DIR}/missing_products.csv"
        s3.download_file(S3_BUCKET, f"{S3_PREFIX}/missing_products.csv", missing_path)
        logger.info("Downloaded missing_products.csv (%d bytes)", os.path.getsize(missing_path))

        # Step 2: Download Shopify comparison CSVs from S3
        logger.info("=== Merge Step 2: Download Shopify comparison CSVs ===")
        shopify_files = [
            "compare_cosmetic", "compare_elite", "compare_lodoro",
            "compare_multimarcas", "compare_productos", "compare_yauras",
        ]
        downloaded = []
        for name in shopify_files:
            filename = f"{name}.csv"
            local_path = f"{OUTPUT_DIR}/{filename}"
            try:
                s3.download_file(S3_BUCKET, f"{S3_PREFIX}/{filename}", local_path)
                size = os.path.getsize(local_path)
                logger.info("Downloaded %s (%d bytes)", filename, size)
                downloaded.append(name)
            except Exception as e:
                logger.error("Failed to download %s: %s", filename, e)

        # Step 3: Download scrape_*.csv from main comparison pipeline
        logger.info("=== Merge Step 3: Download scrape CSVs from main pipeline ===")
        scrape_files = ["scrape_sairam", "scrape_paris", "scrape_lattafa"]
        for name in scrape_files:
            filename = f"{name}.csv"
            local_path = f"{OUTPUT_DIR}/{filename}"
            try:
                s3.download_file(S3_BUCKET, f"comparisons/{filename}", local_path)
                size = os.path.getsize(local_path)
                logger.info("Downloaded %s (%d bytes)", filename, size)
                downloaded.append(name)
            except Exception as e:
                logger.error("Failed to download %s: %s", filename, e)

        logger.info("Downloaded %d files total", len(downloaded))

        # Step 4: Run fuzzy matchers (sairam, paris, lattafa)
        logger.info("=== Merge Step 4: Fuzzy matchers ===")
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

        # Step 5: Merge all comparisons
        logger.info("=== Merge Step 5: Merge comparisons ===")
        from merge_comparisons import main as merge_main
        merge_main()

        # Step 6: Upload results to S3
        logger.info("=== Merge Step 6: Upload results to S3 ===")
        for filename in os.listdir(OUTPUT_DIR):
            if filename.endswith(".csv") and filename != "missing_products.csv":
                filepath = f"{OUTPUT_DIR}/{filename}"
                s3.upload_file(filepath, S3_BUCKET, f"{S3_PREFIX}/{filename}")
                logger.info("Uploaded %s", filename)

        # Step 7: Upload extra_merged_comparisons.csv to ProcWise missing-products endpoint
        logger.info("=== Merge Step 7: upload_missing_products ===")
        from upload_missing_products import main as upload_missing_products_main
        upload_missing_products_main()

        failures = [(n, e) for n, ok, e in results if not ok]
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
