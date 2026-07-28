# Detection-engine image. Build context is the repo root so shared/ is included.
FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY shared/ ./shared/
COPY engine/ ./engine/

ENV PYTHONUNBUFFERED=1
CMD ["python", "-m", "engine.consumer"]
