FROM python:3.11-slim

WORKDIR /app

# Install curl for health checks
RUN apt-get update && apt-get install -y curl && apt-get clean

# Copy the shared utilities and bot code
COPY shared_utils/ /app/shared_utils/
COPY bot/ /app/bot/
COPY .env /app/

# Install dependencies
RUN pip install -r bot/requirements.txt

# Set the working directory to the bot directory
WORKDIR /app/bot

# Expose the port
EXPOSE 9001

# Start the application (relies on ENV=prod being set in docker-compose)
CMD ["python", "main.py"]
