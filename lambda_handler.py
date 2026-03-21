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

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
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
