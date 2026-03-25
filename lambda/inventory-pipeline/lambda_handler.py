#!/usr/bin/env python3
"""AWS Lambda handler — runs the full Kamal inventory pipeline.

Steps:
  1. download_files   → download supplier files from Chirag's ProcWise, upload to Kamal's
  2. pull_costs (all warehouses in parallel)
     → Gorbea (main), Costanera, Ahumada, Providencia
     → all share the same Playwright BSale session cookie
  3. generate_catalog (all warehouses in parallel)
  4. upload_inventory (all warehouses in parallel)
  5. Upload main catalog.csv to S3 for the comparison pipeline
  6. Trigger comparison pipeline (morning run only)
"""

import json
import logging
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed

# Lambda writes to /tmp
os.environ.setdefault("OUTPUT_DIR", "/tmp/output")
os.environ.setdefault("REPLACE_IF_EXISTS", "1")
os.makedirs(os.environ["OUTPUT_DIR"], exist_ok=True)

# Lambda pre-configures the root logger, so basicConfig is ignored.
# Override the root logger directly so all modules' logging.info() calls show up.
root = logging.getLogger()
root.setLevel(logging.INFO)
if root.handlers:
    for h in root.handlers:
        h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S"))
logger = logging.getLogger(__name__)

WAREHOUSES = ["costanera", "ahumada", "providencia"]


def run_step(name, func):
    """Run a step and return (name, success, error)."""
    try:
        logger.info("Starting %s", name)
        func()
        logger.info("Completed %s", name)
        return (name, True, None)
    except Exception as e:
        logger.error("Failed %s: %s", name, e, exc_info=True)
        return (name, False, str(e))


def run_parallel(tasks):
    """Run a list of (name, func) tasks in parallel, return results."""
    results = []
    with ThreadPoolExecutor(max_workers=len(tasks)) as executor:
        futures = {
            executor.submit(run_step, name, func): name
            for name, func in tasks
        }
        for future in as_completed(futures):
            results.append(future.result())
    return results


def handler(event, context):
    """Lambda entry point."""
    try:
        # Step 1: Download supplier files
        logger.info("=== Step 1: download_files ===")
        from download_files import main as download_files_main
        download_files_main()

        # Step 2: Pull costs — main warehouse + 3 additional warehouses in parallel
        # All use the same BSale session cookie. Get it once via Playwright,
        # then share via env var so the scripts don't each launch a browser.
        logger.info("=== Step 2: pull_costs (all warehouses) ===")
        from bsale_session import get_session_cookie_from_env
        cookie = get_session_cookie_from_env()
        os.environ["BSALE_SESSION_COOKIE"] = cookie
        logger.info("BSale session cookie obtained, shared to all warehouses")

        from pull_costs import main as pull_costs_main
        from pull_costs_costanera import main as pull_costs_costanera
        from pull_costs_ahumada import main as pull_costs_ahumada
        from pull_costs_providencia import main as pull_costs_providencia

        cost_results = run_parallel([
            ("pull_costs_gorbea", pull_costs_main),
            ("pull_costs_costanera", pull_costs_costanera),
            ("pull_costs_ahumada", pull_costs_ahumada),
            ("pull_costs_providencia", pull_costs_providencia),
        ])

        # Step 3: Generate catalogs — sequential because all 4 hit the same
        # BSale API (rate limit 8 req/s). Running in parallel causes 429s.
        logger.info("=== Step 3: generate_catalog (all warehouses, sequential) ===")
        from generate_catalog import main as generate_catalog_main
        from generate_catalog_costanera import main as gen_costanera
        from generate_catalog_ahumada import main as gen_ahumada
        from generate_catalog_providencia import main as gen_providencia

        catalog_results = []
        for name, func in [
            ("generate_catalog_gorbea", generate_catalog_main),
            ("generate_catalog_costanera", gen_costanera),
            ("generate_catalog_ahumada", gen_ahumada),
            ("generate_catalog_providencia", gen_providencia),
        ]:
            catalog_results.append(run_step(name, func))

        # Step 4: Upload inventory — all warehouses in parallel
        logger.info("=== Step 4: upload_inventory (all warehouses) ===")
        from upload_inventory import main as upload_inventory_main
        from upload_inventory_costanera import main as upload_costanera
        from upload_inventory_ahumada import main as upload_ahumada
        from upload_inventory_providencia import main as upload_providencia

        upload_results = run_parallel([
            ("upload_inventory_gorbea", upload_inventory_main),
            ("upload_inventory_costanera", upload_costanera),
            ("upload_inventory_ahumada", upload_ahumada),
            ("upload_inventory_providencia", upload_providencia),
        ])

        all_results = cost_results + catalog_results + upload_results

        # Step 5: Upload main catalog.csv to S3 for the comparison pipeline
        s3_bucket = os.environ.get("S3_BUCKET", "kamal-automation-data")
        if s3_bucket:
            logger.info("=== Step 5: uploading catalog.csv to S3 ===")
            import boto3
            s3 = boto3.client("s3")
            output_dir = os.environ.get("OUTPUT_DIR", "/tmp/output")
            s3.upload_file(f"{output_dir}/catalog.csv", s3_bucket, "catalog.csv")
            logger.info("Uploaded catalog.csv to s3://%s/catalog.csv", s3_bucket)

        # Step 6: Trigger comparison pipeline if this is the morning run
        if event.get("trigger_comparison"):
            logger.info("=== Step 6: Triggering comparison pipeline ===")
            import boto3
            lam = boto3.client("lambda")
            lam.invoke(
                FunctionName="kamal-comparison-pipeline",
                InvocationType="Event",
            )
            logger.info("Comparison pipeline triggered (async)")

        failures = [(n, e) for n, ok, e in all_results if not ok]
        if failures:
            logger.warning("Some steps failed: %s", [n for n, _ in failures])

        return {
            "statusCode": 200,
            "body": json.dumps({
                "message": "Pipeline completed",
                "completed": len([r for r in all_results if r[1]]),
                "failed": len(failures),
                "failures": [n for n, _ in failures],
            }),
        }

    except Exception as e:
        logger.exception("Pipeline failed")
        return {
            "statusCode": 500,
            "body": json.dumps({"error": str(e)}),
        }
