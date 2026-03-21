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

## AWS Resources (shared)

| Resource | Name |
|----------|------|
| **IAM Role (Lambda)** | `kamal-inventory-lambda-role` |
| **IAM Role (Scheduler)** | `kamal-scheduler-role` |
| **CloudWatch Log Group** | `/aws/lambda/kamal-inventory-pipeline` |
| **EventBridge Schedule** | `kamal-inventory-morning` (8:30 AM Chile) |
| **EventBridge Schedule** | `kamal-inventory-afternoon` (4:30 PM Chile) |
