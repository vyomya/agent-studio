# Minimal Dockerfile for the FastAPI skeleton app
# Uses Python 3.12 slim base, installs FastAPI and Uvicorn.
FROM python:3.12-slim

WORKDIR /app

# Copy application source
COPY . /app

# Install dependencies
RUN pip install --no-cache-dir fastapi uvicorn

EXPOSE 8000

# Run the app with uvicorn
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]

