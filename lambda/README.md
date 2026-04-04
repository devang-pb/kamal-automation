# Lambda Functions

Each subfolder contains the Dockerfile, handler, and dependencies for one AWS Lambda function. All deployed to account **021891608382** (region `us-east-1`).

## Functions

### `inventory-pipeline/`
Runs the full inventory pipeline: pull costs → generate catalog → upload to ProcWise.

| Property | Value |
|----------|-------|
| **Function name** | `kamal-inventory-pipeline` |
| **Runtime** | Container image (Python 3.12 + Playwright + Chromium) |
| **Timeout** | 900s (15 min) |
| **Memory** | 2048 MB |
| **Typical duration** | ~115s |
| **Schedule** | 8:30 AM & 4:30 PM Chile daily (EventBridge) |
| **ECR repo** | `021891608382.dkr.ecr.us-east-1.amazonaws.com/kamal/inventory-pipeline` |

#### Files
- `Dockerfile` — Container image definition
- `lambda_handler.py` — Entry point, runs the 3 inventory scripts in sequence
- `requirements-lambda.txt` — Python dependencies

#### Build & Deploy
Build from the **project root** (not from this folder):
```bash
export AWS_ACCESS_KEY_ID=<key>
export AWS_SECRET_ACCESS_KEY=<secret>

aws ecr get-login-password --region us-east-1 | \
  docker login --username AWS --password-stdin 021891608382.dkr.ecr.us-east-1.amazonaws.com

docker build --platform linux/amd64 --provenance=false \
  -f lambda/inventory-pipeline/Dockerfile \
  -t 021891608382.dkr.ecr.us-east-1.amazonaws.com/kamal/inventory-pipeline:latest .

docker push 021891608382.dkr.ecr.us-east-1.amazonaws.com/kamal/inventory-pipeline:latest

aws lambda update-function-code \
  --function-name kamal-inventory-pipeline \
  --image-uri 021891608382.dkr.ecr.us-east-1.amazonaws.com/kamal/inventory-pipeline:latest \
  --region us-east-1
```

#### Invoke
```bash
# Sync (wait ~2 min)
aws lambda invoke --function-name kamal-inventory-pipeline \
  --cli-read-timeout 900 --region us-east-1 response.json

# Async
aws lambda invoke --function-name kamal-inventory-pipeline \
  --invocation-type Event --region us-east-1 response.json
```

### `comparison-pipeline/`
Runs the price comparison pipeline: scrapes 3 competitor sites, compares prices across 6 Shopify stores, runs fuzzy matchers, merges results, and uploads to ProcWise + S3.

| Property | Value |
|----------|-------|
| **Function name** | `kamal-comparison-pipeline` |
| **Runtime** | Container image (Python 3.12) |
| **Timeout** | 900s (15 min) |
| **Memory** | 2048 MB |
| **Typical duration** | ~246s (dispatch), ~7s (merge), ~500-750s (workers) |
| **Triggered by** | `kamal-inventory-pipeline` (morning+afternoon dispatch) + EventBridge (noon dispatch) + EventBridge (merges) |
| **ECR repo** | `021891608382.dkr.ecr.us-east-1.amazonaws.com/kamal/comparison-pipeline` |

#### Architecture (two-phase pipeline)
The handler supports three modes via the event payload:

- **`mode="full"`** (default) — Dispatch phase: runs 3 scrapers locally, fires 6 async Shopify worker Lambdas (1 per store), uploads scraper results to S3. Completes in ~4 min.
- **`mode="shopify_worker"`** — Worker: runs one Shopify store compare, uploads CSV to S3. Each worker gets its own 900s budget. Rate-limited stores (lodoro, productos, yauras) use 2 threads; others use 3, with 0.15s per-request throttle to avoid 429s.
- **`mode="merge"`** — Merge phase: downloads all CSVs from S3, runs fuzzy matchers (sairam, paris, lattafa), merges everything, uploads to ProcWise + S3. Completes in ~7s. Triggered by EventBridge at 8:45 AM Chile (15 min after dispatch).

This two-phase pattern ensures no single Lambda is close to the 900s timeout. Workers run independently with their full budget, and the merge runs only after all workers have completed.

#### Build & Deploy
Build from the **project root** (not from this folder):
```bash
docker build --platform linux/amd64 --provenance=false \
  -f lambda/comparison-pipeline/Dockerfile \
  -t 021891608382.dkr.ecr.us-east-1.amazonaws.com/kamal/comparison-pipeline:latest .

docker push 021891608382.dkr.ecr.us-east-1.amazonaws.com/kamal/comparison-pipeline:latest

aws lambda update-function-code \
  --function-name kamal-comparison-pipeline \
  --image-uri 021891608382.dkr.ecr.us-east-1.amazonaws.com/kamal/comparison-pipeline:latest \
  --region us-east-1
```

#### Invoke
```bash
# Dispatch (scrapers + fire workers) — async
aws lambda invoke --function-name kamal-comparison-pipeline \
  --invocation-type Event --region us-east-1 response.json

# Merge (after workers are done) — sync
aws lambda invoke --function-name kamal-comparison-pipeline \
  --cli-read-timeout 60 --cli-binary-format raw-in-base64-out \
  --payload '{"mode":"merge"}' --region us-east-1 response.json
```

### `extra-comparison-pipeline/`
Runs price comparisons for products missing from the main catalog. Uses `missing_products.csv` (from ProcWise's missing-eans endpoint) instead of `catalog.csv`.

| Property | Value |
|----------|-------|
| **Function name** | `kamal-extra-comparison-pipeline` |
| **Runtime** | Container image (Python 3.12) |
| **Timeout** | 900s (15 min) |
| **Memory** | 2048 MB |
| **ECR repo** | `021891608382.dkr.ecr.us-east-1.amazonaws.com/kamal/extra-comparison-pipeline` |

#### Architecture (two-phase pipeline)
Same pattern as the comparison pipeline:

- **`mode="full"`** (default) — Dispatch: runs `get_missing_products`, uploads `missing_products.csv` to S3, fires 6 async Shopify worker Lambdas.
- **`mode="shopify_worker"`** — Worker: runs specified Shopify store compares against missing products, uploads CSVs to S3.
- **`mode="merge"`** — Downloads Shopify CSVs + `scrape_*.csv` from the main pipeline, runs 3 fuzzy matchers, merges into `extra_merged_comparisons.csv`, uploads to S3.

#### Build & Deploy
Build from the **project root**:
```bash
docker build --platform linux/amd64 --provenance=false \
  -f lambda/extra-comparison-pipeline/Dockerfile \
  -t 021891608382.dkr.ecr.us-east-1.amazonaws.com/kamal/extra-comparison-pipeline:latest .

docker push 021891608382.dkr.ecr.us-east-1.amazonaws.com/kamal/extra-comparison-pipeline:latest

aws lambda update-function-code \
  --function-name kamal-extra-comparison-pipeline \
  --image-uri 021891608382.dkr.ecr.us-east-1.amazonaws.com/kamal/extra-comparison-pipeline:latest \
  --region us-east-1
```

#### Invoke
```bash
# Dispatch (get missing products + fire workers) — sync
aws lambda invoke --function-name kamal-extra-comparison-pipeline \
  --cli-read-timeout 900 --region us-east-1 response.json

# Merge (after workers are done) — sync
aws lambda invoke --function-name kamal-extra-comparison-pipeline \
  --cli-read-timeout 60 --cli-binary-format raw-in-base64-out \
  --payload '{"mode":"merge"}' --region us-east-1 response.json
```

## AWS Resources (shared)

| Resource | Name |
|----------|------|
| **IAM Role (Lambda)** | `kamal-inventory-lambda-role` |
| **IAM Role (Scheduler)** | `kamal-scheduler-role` |

### Daily Schedule (Chile time)

| Time | Lambda | Mode | Trigger |
|------|--------|------|---------|
| 8:30 AM | `inventory-pipeline` | full | `kamal-inventory-morning` |
| ~8:32 AM | `comparison-pipeline` | full (dispatch) | Triggered by inventory |
| 8:45 AM | `comparison-pipeline` | merge | `kamal-comparison-merge-morning` |
| 8:50 AM | `extra-comparison-pipeline` | full (dispatch) | `kamal-extra-comparison-dispatch-morning` |
| 9:05 AM | `extra-comparison-pipeline` | merge | `kamal-extra-comparison-merge-morning` |
| 12:00 PM | `comparison-pipeline` | full (dispatch) | `kamal-comparison-dispatch-noon` |
| 12:15 PM | `comparison-pipeline` | merge | `kamal-comparison-merge-noon` |
| 12:20 PM | `extra-comparison-pipeline` | full (dispatch) | `kamal-extra-comparison-dispatch-noon` |
| 12:35 PM | `extra-comparison-pipeline` | merge | `kamal-extra-comparison-merge-noon` |
| 4:30 PM | `inventory-pipeline` | full | `kamal-inventory-afternoon` |
| ~4:32 PM | `comparison-pipeline` | full (dispatch) | Triggered by inventory |
| 4:45 PM | `comparison-pipeline` | merge | `kamal-comparison-merge-afternoon` |
| 4:50 PM | `extra-comparison-pipeline` | full (dispatch) | `kamal-extra-comparison-dispatch-afternoon` |
| 5:05 PM | `extra-comparison-pipeline` | merge | `kamal-extra-comparison-merge-afternoon` |
