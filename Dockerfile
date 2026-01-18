FROM python:3.11-slim

WORKDIR /app

# Install system dependencies if needed (none strictly required for basic scrape, 
# but good to have git or curl sometimes)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Run unbuffered to see logs in Docker
ENV PYTHONUNBUFFERED=1

CMD ["python", "scraper.py"]
