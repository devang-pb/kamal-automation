FROM public.ecr.aws/lambda/python:3.12

# Install system deps for Playwright Chromium
RUN dnf install -y \
    alsa-lib atk at-spi2-atk cups-libs libdrm libXcomposite libXdamage \
    libXrandr mesa-libgbm pango nss gtk3 libXScrnSaver \
    && dnf clean all

# Install Python dependencies
COPY lambda/inventory-pipeline/requirements-lambda.txt .
RUN pip install --no-cache-dir -r requirements-lambda.txt

# Install Playwright Chromium in a fixed path accessible at runtime
ENV PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers
RUN playwright install chromium

# Copy application code
COPY inventory/bsale_client.py inventory/bsale_session.py inventory/pull_costs.py \
     inventory/generate_catalog.py inventory/upload_inventory.py \
     lambda/inventory-pipeline/lambda_handler.py ./

# Set Lambda handler
CMD ["lambda_handler.handler"]
