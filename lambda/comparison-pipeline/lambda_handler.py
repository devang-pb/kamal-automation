#!/usr/bin/env python3
"""AWS Lambda handler — runs the full price comparison pipeline.

Steps:
  1. Download catalog.csv from S3
  2. Run 3 scrapers in parallel (different sites, no conflict)
  3. Run 6 Shopify compares sequentially (same Shopify API, avoid 429 storms)
  4. Run 3 fuzzy matchers
  5. Merge all comparisons
  6. Upload results to S3
"""

import json
import logging
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed

OUTPUT_DIR = "/tmp/output"
os.environ["OUTPUT_DIR"] = OUTPUT_DIR
os.environ["COMPARE_MAX_WORKERS"] = "6"  # Reduce threads per compare script
os.makedirs(OUTPUT_DIR, exist_ok=True)

# Configure logging for CloudWatch
root = logging.getLogger()
root.setLevel(logging.INFO)
if root.handlers:
    for h in root.handlers:
        h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S"))
logger = logging.getLogger(__name__)

S3_BUCKET = os.environ.get("S3_BUCKET", "kamal-automation-data")


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


def handler(event, context):
    """Lambda entry point."""
    try:
        # Step 1: Download catalog.csv from S3
        logger.info("=== Step 1: Download catalog.csv from S3 ===")
        import boto3
        s3 = boto3.client("s3")
        catalog_path = f"{OUTPUT_DIR}/catalog.csv"
        s3.download_file(S3_BUCKET, "catalog.csv", catalog_path)
        logger.info("Downloaded catalog.csv (%d bytes)", os.path.getsize(catalog_path))

        # Step 2: Run 3 scrapers in parallel (different sites, no rate limit conflict)
        logger.info("=== Step 2: Scrapers (parallel) ===")
        from scrape_sairam import run as sairam_scrape
        from scrape_paris import run as paris_scrape
        from scrape_lattafa import run as lattafa_scrape

        scraper_results = []
        with ThreadPoolExecutor(max_workers=3) as executor:
            futures = {
                executor.submit(run_script, name, func): name
                for name, func in [
                    ("scrape_sairam", sairam_scrape),
                    ("scrape_paris", paris_scrape),
                    ("scrape_lattafa", lattafa_scrape),
                ]
            }
            for future in as_completed(futures):
                scraper_results.append(future.result())

        # Step 3: Run 6 Shopify compares sequentially
        # Each site rate-limits independently, but running all 6 in parallel
        # with threads causes 429 storms that slow everything down.
        logger.info("=== Step 3: Shopify compares (sequential) ===")
        from compare_cosmetic import main as cosmetic_main
        from compare_elite import main as elite_main
        from compare_lodoro import main as lodoro_main
        from compare_multimarcas import main as multimarcas_main
        from compare_productos import main as productos_main
        from compare_yauras import main as yauras_main

        compare_results = []
        for name, func in [
            ("compare_cosmetic", cosmetic_main),
            ("compare_elite", elite_main),
            ("compare_lodoro", lodoro_main),
            ("compare_multimarcas", multimarcas_main),
            ("compare_productos", productos_main),
            ("compare_yauras", yauras_main),
        ]:
            compare_results.append(run_script(name, func))

        all_results = scraper_results + compare_results

        # Step 4: Run fuzzy matchers
        logger.info("=== Step 4: Fuzzy matchers ===")
        from compare_sairam import main as sairam_compare
        from compare_paris import main as paris_compare
        from compare_lattafa import main as lattafa_compare

        for name, func in [
            ("compare_sairam", sairam_compare),
            ("compare_paris", paris_compare),
            ("compare_lattafa", lattafa_compare),
        ]:
            run_script(name, func)

        # Step 5: Merge
        logger.info("=== Step 5: Merge comparisons ===")
        from merge_comparisons import main as merge_main
        merge_main()

        # Step 6: Upload results to S3
        logger.info("=== Step 6: Upload results to S3 ===")
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

    except Exception as e:
        logger.exception("Pipeline failed")
        return {
            "statusCode": 500,
            "body": json.dumps({"error": str(e)}),
        }
