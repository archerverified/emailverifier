FROM python:3.11-slim

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

CMD ["python", "app.py"]
