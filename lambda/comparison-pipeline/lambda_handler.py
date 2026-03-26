#!/usr/bin/env python3
"""AWS Lambda handler — runs the full price comparison pipeline.

Supports two modes via the event payload:

  mode="full" (default):
    Orchestrator — runs scrapers locally, invokes 2 worker instances of
    itself for Shopify compares (3 stores each, sequential within each
    worker), then runs fuzzy matchers, merge, and upload.

  mode="shopify_worker":
    Worker — runs the specified Shopify compares sequentially and uploads
    the result CSVs to S3. Invoked by the orchestrator.

This avoids 429 storms (all 6 Shopify stores concurrent = too many requests)
while cutting total time from ~880s to ~330s by running the two worker
Lambda instances in parallel with the scrapers.
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

# Map of store name → (compare script module, main function name)
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
    """Lambda entry point — dispatches to worker or full pipeline."""
    mode = event.get("mode", "full")
    if mode == "shopify_worker":
        return _shopify_worker(event)
    return _full_pipeline(event, context)


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


def _invoke_shopify_worker(lambda_client, stores, max_workers=None):
    """Synchronously invoke this Lambda in worker mode for a batch of stores."""
    logger.info("Invoking worker for stores: %s (threads=%s)", stores, max_workers or "default")
    payload = {"mode": "shopify_worker", "stores": stores}
    if max_workers:
        payload["max_workers"] = max_workers
    response = lambda_client.invoke(
        FunctionName=FUNCTION_NAME,
        InvocationType="RequestResponse",
        Payload=json.dumps(payload),
    )
    payload = json.loads(response["Payload"].read())
    status = response.get("StatusCode", 0)
    if status != 200 or payload.get("statusCode") != 200:
        raise RuntimeError(f"Worker failed for {stores}: {payload}")
    logger.info("Worker completed for stores: %s", stores)
    return payload


def _full_pipeline(event, context):
    """Full pipeline: scrapers + 2 worker invocations + fuzzy + merge + upload."""
    try:
        import boto3
        from botocore.config import Config

        s3 = boto3.client("s3")
        lambda_client = boto3.client(
            "lambda",
            config=Config(read_timeout=900, connect_timeout=10),
        )

        # Step 1: Download catalog.csv from S3
        logger.info("=== Step 1: Download catalog.csv from S3 ===")
        catalog_path = f"{OUTPUT_DIR}/catalog.csv"
        s3.download_file(S3_BUCKET, "catalog.csv", catalog_path)
        logger.info("Downloaded catalog.csv (%d bytes)", os.path.getsize(catalog_path))

        # Step 2: Run scrapers + 2 Shopify worker Lambdas in parallel
        # Scrapers run locally (3 threads). Shopify compares are offloaded to
        # 2 separate Lambda instances (3 stores each, sequential within each)
        # so they don't share the same process / rate limit pool.
        logger.info("=== Step 2: Scrapers (local) + Shopify workers (2 Lambdas) ===")
        from scrape_sairam import run as sairam_scrape
        from scrape_paris import run as paris_scrape
        from scrape_lattafa import run as lattafa_scrape

        all_results = []
        with ThreadPoolExecutor(max_workers=9) as executor:
            futures = {
                # 3 scrapers (local)
                executor.submit(run_script, "scrape_sairam", sairam_scrape): "scrape_sairam",
                executor.submit(run_script, "scrape_paris", paris_scrape): "scrape_paris",
                executor.submit(run_script, "scrape_lattafa", lattafa_scrape): "scrape_lattafa",
                # 6 Shopify worker Lambdas (1 store each to fit within 900s)
                executor.submit(
                    _invoke_shopify_worker, lambda_client, ["cosmetic"],
                ): "shopify_cosmetic",
                executor.submit(
                    _invoke_shopify_worker, lambda_client, ["elite"],
                ): "shopify_elite",
                executor.submit(
                    _invoke_shopify_worker, lambda_client, ["lodoro"], 2,
                ): "shopify_lodoro",
                executor.submit(
                    _invoke_shopify_worker, lambda_client, ["multimarcas"],
                ): "shopify_multimarcas",
                executor.submit(
                    _invoke_shopify_worker, lambda_client, ["productos"], 2,
                ): "shopify_productos",
                executor.submit(
                    _invoke_shopify_worker, lambda_client, ["yauras"], 2,
                ): "shopify_yauras",
            }
            for future in as_completed(futures):
                name = futures[future]
                try:
                    result = future.result()
                    if isinstance(result, tuple):
                        # Scraper result: (name, success, error)
                        all_results.append(result)
                    else:
                        # Worker result: dict with failures list
                        worker_failures = result.get("body", "{}")
                        if isinstance(worker_failures, str):
                            worker_failures = json.loads(worker_failures)
                        failed = worker_failures.get("failures", [])
                        stores = worker_failures.get("stores", [])
                        for store in stores:
                            ok = f"compare_{store}" not in failed
                            all_results.append((f"compare_{store}", ok, None if ok else "failed in worker"))
                except Exception as e:
                    logger.error("Task %s raised: %s", name, e)
                    all_results.append((name, False, str(e)))

        # Step 3: Download Shopify compare results from S3
        logger.info("=== Step 3: Download Shopify results from S3 ===")
        for store in SHOPIFY_STORES:
            filename = f"compare_{store}.csv"
            local_path = f"{OUTPUT_DIR}/{filename}"
            try:
                s3.download_file(S3_BUCKET, f"comparisons/{filename}", local_path)
                logger.info("Downloaded %s (%d bytes)", filename, os.path.getsize(local_path))
            except Exception as e:
                logger.error("Failed to download %s: %s", filename, e)

        # Step 4: Run fuzzy matchers (depend on scraper output from step 2)
        logger.info("=== Step 4: Fuzzy matchers ===")
        from compare_sairam import main as sairam_compare
        from compare_paris import main as paris_compare
        from compare_lattafa import main as lattafa_compare

        for name, func in [
            ("compare_sairam", sairam_compare),
            ("compare_paris", paris_compare),
            ("compare_lattafa", lattafa_compare),
        ]:
            all_results.append(run_script(name, func))

        # Step 5: Merge
        logger.info("=== Step 5: Merge comparisons ===")
        from merge_comparisons import main as merge_main
        merge_main()

        # Step 6: Upload to ProcWise
        logger.info("=== Step 6: Upload retail intel to ProcWise ===")
        try:
            from upload_retail_intel import main as upload_retail_intel_main
            upload_retail_intel_main()
            logger.info("ProcWise upload completed")
        except Exception as e:
            logger.error("ProcWise upload failed: %s", e, exc_info=True)

        # Step 7: Upload results to S3
        logger.info("=== Step 7: Upload results to S3 ===")
        for filename in os.listdir(OUTPUT_DIR):
            if filename.endswith(".csv") and filename != "catalog.csv":
                filepath = f"{OUTPUT_DIR}/{filename}"
                s3.upload_file(filepath, S3_BUCKET, f"comparisons/{filename}")
                logger.info("Uploaded %s", filename)

        failures = [(n, e) for n, ok, e in all_results if not ok]
        summary = {
            "completed": len([r for r in all_results if r[1]]),
            "failed": len(failures),
            "failures": [name for name, _ in failures],
        }
        return {
            "statusCode": 200,
            "body": json.dumps({"message": "Comparison pipeline completed", **summary}),
        }

    except (Exception, SystemExit) as e:
        logger.exception("Pipeline failed")
        return {
            "statusCode": 500,
            "body": json.dumps({"error": str(e)}),
        }
