# Playwright Lambda Container
FROM mcr.microsoft.com/playwright/python:v1.48.0-noble

# Set working directory
WORKDIR /var/task

# Install AWS Lambda runtime interface client
RUN pip install --no-cache-dir awslambdaric

# Copy and install requirements
COPY src/summarizer_handler/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY src/summarizer_handler/*.py ./summarizer_handler/
COPY src/common/*.py ./common/

# Create __init__.py files
RUN touch ./summarizer_handler/__init__.py ./common/__init__.py

# Set environment for Lambda
ENV HOME=/tmp
ENV PYTHONPATH=/var/task
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

# Entry point for Lambda
ENTRYPOINT [ "python", "-m", "awslambdaric" ]
CMD [ "summarizer_handler.handler.lambda_handler" ]
