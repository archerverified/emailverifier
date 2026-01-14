FROM python:3.11-slim

# Install curl for healthcheck
RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy backend requirements and install
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy backend code
COPY backend/*.py ./
COPY backend/tests ./tests/

# Copy frontend files to serve them
COPY frontend/ ./frontend/

# Copy scripts
COPY scripts/ ./scripts/

# Copy sample data for smoke tests
COPY Fortune500leads.csv ./

# Expose port
EXPOSE 5050

# Set default to real mode (can override in docker-compose)
ENV VALIDATOR_MODE=real

CMD ["sh", "-c", "gunicorn -w ${GUNICORN_WORKERS:-1} --threads ${GUNICORN_THREADS:-8} -k gthread -t ${GUNICORN_TIMEOUT:-180} -b 0.0.0.0:5050 app:app"]
