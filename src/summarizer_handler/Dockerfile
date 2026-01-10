# Playwright Lambda Container
FROM mcr.microsoft.com/playwright/python:v1.40.0-focal

# Set working directory
WORKDIR /var/task

# Install AWS Lambda runtime interface client
RUN pip install --no-cache-dir awslambdaric boto3 anthropic

# Install additional dependencies
RUN pip install --no-cache-dir aiohttp

# Copy handler code
COPY handler.py /var/task/
COPY extractor.py /var/task/
COPY summarizer.py /var/task/

# Set the entrypoint
ENTRYPOINT [ "python", "-m", "awslambdaric" ]
CMD [ "handler.lambda_handler" ]
