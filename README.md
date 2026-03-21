# Kamal Inventory Automation

Automated pipeline for Kamal's perfume warehouse (SILK PERFUMES) — pulls inventory data from BSale, generates a catalog, and uploads it to the ProcWise platform. Runs daily on AWS Lambda.

---

## Scripts

### Core Pipeline (runs on Lambda)

These three scripts run sequentially as the Lambda pipeline:

| # | Script | What it does |
|---|--------|-------------|
| 1 | `pull_costs.py` | Logs into BSale via Playwright (headless Chromium), navigates to the Stock report, and scrapes cost + brand data for every EAN in the Gorbea warehouse. Outputs `output/costs.csv` (columns: `ean`, `avg_cost`, `brand`). |
| 2 | `generate_catalog.py` | Calls the BSale REST API to fetch stock quantities (office 1 / Gorbea), base price list (list 2), and variant details. Joins with `costs.csv` to produce `output/catalog.csv` (columns: `ean`, `sku`, `name`, `stock`, `price`, `avg_cost`, `brand`). |
| 3 | `upload_inventory.py` | Reads `catalog.csv`, logs into ProcWise, sends the column map, and uploads all inventory items. |

### Supporting Modules

| Module | Purpose |
|--------|---------|
| `bsale_session.py` | Playwright-based login to BSale. Navigates login → company selection (cpn 67758) → Stock module to capture the `bsale-session` cookie for the stock report API. |
| `bsale_client.py` | HTTP client for the BSale REST API (`api.bsale.cl`). Handles auth (token header), pagination, rate limiting (8 req/s), and retries. |
| `lambda_handler.py` | AWS Lambda entry point. Configures logging for CloudWatch, sets `OUTPUT_DIR=/tmp/output`, and runs the three pipeline scripts in sequence. |

### Other Scripts (not on Lambda)

| Script | Purpose |
|--------|---------|
| `download_excels.py` | Fetches 7 supplier price list files into `downloads/` |
| `compare_*.py` (6 scripts) | Compare inventory against suppliers: cosmetic, productos, lodoro, multimarcas, elite, yauras |
| `scrape_*.py` (3 scripts) | Scrape supplier data: sairam, paris, lattafa |
| `merge_comparisons.py` | Merges all comparison results into a single output |
| `generate_catalog_costanera.py` | Catalog generation for the Costanera warehouse |
| `pull_costs_costanera.py` | Cost pulling for the Costanera warehouse |

---

## AWS Infrastructure

All resources are on AWS account **021891608382** (user: `info-telecast`), region **us-east-1**.

### Lambda Function

| Property | Value |
|----------|-------|
| **Name** | `kamal-inventory-pipeline` |
| **ARN** | `arn:aws:lambda:us-east-1:021891608382:function:kamal-inventory-pipeline` |
| **Runtime** | Container image (Python 3.12 + Playwright + Chromium) |
| **Timeout** | 900 seconds (15 minutes) |
| **Memory** | 2048 MB |
| **Typical duration** | ~115 seconds |
| **Peak memory usage** | ~920 MB |

#### Environment Variables

| Variable | Description |
|----------|-------------|
| `BSALE_API_TOKEN` | BSale REST API token |
| `BSALE_BASE_URL` | `https://api.bsale.cl` |
| `BSALE_EMAIL` | BSale login email (for Playwright session) |
| `BSALE_PASSWORD` | BSale login password |
| `PROCWISE_EMAIL` | ProcWise platform login email |
| `PROCWISE_PASSWORD` | ProcWise platform login password |
| `OUTPUT_DIR` | `/tmp/output` (Lambda writable directory) |
| `PLAYWRIGHT_BROWSERS_PATH` | `/opt/pw-browsers` (where Chromium is installed in the container) |

### ECR Repository

| Property | Value |
|----------|-------|
| **Name** | `kamal/inventory-pipeline` |
| **URI** | `021891608382.dkr.ecr.us-east-1.amazonaws.com/kamal/inventory-pipeline` |

### IAM Roles

| Role | Purpose | Policies |
|------|---------|----------|
| `kamal-inventory-lambda-role` | Lambda execution role | `AWSLambdaBasicExecutionRole` (CloudWatch Logs) |
| `kamal-scheduler-role` | EventBridge Scheduler role | Inline `invoke-lambda` policy → can invoke `kamal-inventory-pipeline` |

### EventBridge Schedules

| Schedule Name | Time (Chile) | Cron Expression | Timezone |
|--------------|-------------|-----------------|----------|
| `kamal-inventory-morning` | 8:30 AM daily | `cron(30 8 * * ? *)` | `America/Santiago` |
| `kamal-inventory-afternoon` | 4:30 PM daily | `cron(30 16 * * ? *)` | `America/Santiago` |

### CloudWatch Logs

| Property | Value |
|----------|-------|
| **Log group** | `/aws/lambda/kamal-inventory-pipeline` |
| **Log format** | `HH:MM:SS LEVEL message` — all three scripts log detailed progress |

---

## Docker Image

The Lambda runs as a container image. Key files:

- **`Dockerfile`** — Based on `public.ecr.aws/lambda/python:3.12`. Installs system libs for Chromium, Python deps, Playwright browsers, and application code.
- **`requirements-lambda.txt`** — `requests`, `python-dotenv`, `playwright`

### Building and Deploying

```bash
# Set credentials for Kamal's AWS account
export AWS_ACCESS_KEY_ID=<key>
export AWS_SECRET_ACCESS_KEY=<secret>

# Login to ECR
aws ecr get-login-password --region us-east-1 | \
  docker login --username AWS --password-stdin 021891608382.dkr.ecr.us-east-1.amazonaws.com

# Build for Lambda (must be linux/amd64)
docker build --platform linux/amd64 --provenance=false \
  -t 021891608382.dkr.ecr.us-east-1.amazonaws.com/kamal/inventory-pipeline:latest .

# Push
docker push 021891608382.dkr.ecr.us-east-1.amazonaws.com/kamal/inventory-pipeline:latest

# Update Lambda to use new image
aws lambda update-function-code \
  --function-name kamal-inventory-pipeline \
  --image-uri 021891608382.dkr.ecr.us-east-1.amazonaws.com/kamal/inventory-pipeline:latest \
  --region us-east-1
```

### Manual Invocation

```bash
# Synchronous (wait for result — use long timeout since pipeline takes ~2 min)
aws lambda invoke \
  --function-name kamal-inventory-pipeline \
  --cli-read-timeout 900 \
  --region us-east-1 \
  response.json

# Asynchronous (fire and forget — check CloudWatch for results)
aws lambda invoke \
  --function-name kamal-inventory-pipeline \
  --invocation-type Event \
  --region us-east-1 \
  response.json
```

---

## Local Development

### Prerequisites

- Python 3.12 (via conda: `conda activate py312`)
- Playwright browsers: `playwright install chromium`
- `.env` file with all credentials

### Running Locally

```bash
conda activate base && conda activate py312
python pull_costs.py
python generate_catalog.py
python upload_inventory.py
```

Output files are written to `output/` locally (vs `/tmp/output/` on Lambda).
