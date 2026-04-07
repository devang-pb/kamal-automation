FROM public.ecr.aws/lambda/python:3.12

# Install Python dependencies
COPY lambda/comparison-pipeline/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy comparison scripts
COPY comparisons/compare_cosmetic.py comparisons/compare_elite.py \
     comparisons/compare_lodoro.py comparisons/compare_multimarcas.py \
     comparisons/compare_productos.py comparisons/compare_yauras.py \
     comparisons/compare_lattafa.py comparisons/compare_paris.py \
     comparisons/compare_sairam.py comparisons/merge_comparisons.py \
     comparisons/upload_retail_intel.py comparisons/send_comparison_report.py ./

# Copy scraper scripts
COPY scrapers/scrape_sairam.py scrapers/scrape_paris.py \
     scrapers/scrape_lattafa.py ./

# Copy handler
COPY lambda/comparison-pipeline/lambda_handler.py ./

CMD ["lambda_handler.handler"]
