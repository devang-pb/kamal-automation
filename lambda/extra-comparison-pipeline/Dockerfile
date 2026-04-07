FROM public.ecr.aws/lambda/python:3.12

# Install Python dependencies
COPY lambda/extra-comparison-pipeline/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy extra-comparison scripts
COPY extra-comparisons/get_missing_products.py \
     extra-comparisons/compare_cosmetic.py extra-comparisons/compare_elite.py \
     extra-comparisons/compare_lodoro.py extra-comparisons/compare_multimarcas.py \
     extra-comparisons/compare_productos.py extra-comparisons/compare_yauras.py \
     extra-comparisons/compare_lattafa.py extra-comparisons/compare_paris.py \
     extra-comparisons/compare_sairam.py extra-comparisons/merge_comparisons.py \
     extra-comparisons/upload_missing_products.py \
     ./

# Copy handler
COPY lambda/extra-comparison-pipeline/lambda_handler.py ./

CMD ["lambda_handler.handler"]
