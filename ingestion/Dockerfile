# Ingestion worker image. Build context is the repo root so shared/ is included.
FROM python:3.12-slim

WORKDIR /app

# System deps kept minimal; psycopg[binary] needs no build toolchain.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Source
COPY shared/ ./shared/
COPY ingestion/ ./ingestion/

ENV PYTHONUNBUFFERED=1
CMD ["python", "-m", "ingestion.scheduler"]
