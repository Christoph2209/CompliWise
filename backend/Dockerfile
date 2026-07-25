# --- CompliWise Backend (FastAPI) ---
FROM python:3.11-slim

WORKDIR /app

# System deps needed for psycopg2 / building some Python packages
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    libffi-dev \
    && rm -rf /var/lib/apt/lists/*

# Install Python deps first for better layer caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the backend source
COPY . .

EXPOSE 8000

# NOTE: no --reload in the container — that's a dev-only flag.
# For Compose local dev you can override this command; for staging/demo,
# this is the command that runs.
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]