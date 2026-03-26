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
| **Triggered by** | `kamal-inventory-pipeline` (morning dispatch) + EventBridge (morning merge) |
| **ECR repo** | `021891608382.dkr.ecr.us-east-1.amazonaws.com/kamal/comparison-pipeline` |

#### Architecture (two-phase pipeline)
The handler supports three modes via the event payload:

- **`mode="full"`** (default) — Dispatch phase: runs 3 scrapers locally, fires 6 async Shopify worker Lambdas (1 per store), uploads scraper results to S3. Completes in ~4 min.
- **`mode="shopify_worker"`** — Worker: runs one Shopify store compare, uploads CSV to S3. Each worker gets its own 900s budget. Rate-limited stores (lodoro, productos, yauras) use 2 threads; others use 3, with 0.15s per-request throttle to avoid 429s.
- **`mode="merge"`** — Merge phase: downloads all CSVs from S3, runs fuzzy matchers (sairam, paris, lattafa), merges everything, uploads to ProcWise + S3. Completes in ~7s. Triggered by EventBridge at 8:55 AM Chile (25 min after dispatch).

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

## AWS Resources (shared)

| Resource | Name |
|----------|------|
| **IAM Role (Lambda)** | `kamal-inventory-lambda-role` |
| **IAM Role (Scheduler)** | `kamal-scheduler-role` |
| **CloudWatch Log Group** | `/aws/lambda/kamal-inventory-pipeline` |
| **EventBridge Schedule** | `kamal-inventory-morning` (8:30 AM Chile) |
| **EventBridge Schedule** | `kamal-inventory-afternoon` (4:30 PM Chile) |
| **EventBridge Schedule** | `kamal-comparison-merge-morning` (8:55 AM Chile) |
