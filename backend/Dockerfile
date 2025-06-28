FROM python:3.11-slim

WORKDIR /app

# Install system and Python dependencies (WeasyPrint, etc. if needed)
RUN apt-get update && apt-get install -y \
    curl \
    libpango-1.0-0 \
    libpangoft2-1.0-0 \
    libharfbuzz0b \
    libharfbuzz-subset0 \
    libffi-dev \
    libjpeg-dev \
    libopenjp2-7-dev \
    libxml2 \
    libxslt1.1 \
    libpq-dev \
    libssl-dev \
    gcc \
    --no-install-recommends && \
    rm -rf /var/lib/apt/lists/*

# Copy your app code
COPY shared_utils/ /app/shared_utils/
COPY backend/ /app/backend/
COPY .env /app/

# Install Python requirements
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

WORKDIR /app/backend

EXPOSE 9002

CMD ["python", "main.py"]
