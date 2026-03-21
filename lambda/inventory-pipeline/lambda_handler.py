#!/usr/bin/env python3
"""AWS Lambda handler — runs the full Kamal inventory pipeline.

Steps:
  1. pull_costs   → fetch cost/brand data via BSale stock report (Playwright login)
  2. generate_catalog → build catalog from BSale API + costs
  3. upload_inventory → push catalog to ProcWise
"""

import json
import logging
import os
import sys

# Lambda writes to /tmp
os.environ.setdefault("OUTPUT_DIR", "/tmp/output")

# Lambda pre-configures the root logger, so basicConfig is ignored.
# Override the root logger directly so all modules' logging.info() calls show up.
root = logging.getLogger()
root.setLevel(logging.INFO)
if root.handlers:
    for h in root.handlers:
        h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S"))
logger = logging.getLogger(__name__)


def handler(event, context):
    """Lambda entry point."""
    try:
        # Step 1: Pull costs
        logger.info("=== Step 1/3: pull_costs ===")
        from pull_costs import main as pull_costs_main
        pull_costs_main()

        # Step 2: Generate catalog
        logger.info("=== Step 2/3: generate_catalog ===")
        from generate_catalog import main as generate_catalog_main
        generate_catalog_main()

        # Step 3: Upload inventory
        logger.info("=== Step 3/3: upload_inventory ===")
        from upload_inventory import main as upload_inventory_main
        upload_inventory_main()

        # Step 4: Upload catalog.csv to S3 for the comparison pipeline
        s3_bucket = os.environ.get("S3_BUCKET", "kamal-automation-data")
        if s3_bucket:
            logger.info("=== Step 4/4: uploading catalog.csv to S3 ===")
            import boto3
            s3 = boto3.client("s3")
            output_dir = os.environ.get("OUTPUT_DIR", "/tmp/output")
            s3.upload_file(f"{output_dir}/catalog.csv", s3_bucket, "catalog.csv")
            logger.info("Uploaded catalog.csv to s3://%s/catalog.csv", s3_bucket)

        return {
            "statusCode": 200,
            "body": json.dumps({"message": "Pipeline completed successfully"}),
        }

    except Exception as e:
        logger.exception("Pipeline failed")
        return {
            "statusCode": 500,
            "body": json.dumps({"error": str(e)}),
        }
