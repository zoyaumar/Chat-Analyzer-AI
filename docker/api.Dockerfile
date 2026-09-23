# API image: installs pinned dependencies, applies migrations, starts Uvicorn.
# Only nginx reaches this container (docs/DESIGN_DECISIONS.md Q34/Q41).
FROM python:3.11-slim

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY alembic.ini .
COPY alembic/ alembic/
COPY chat_backend/ chat_backend/

EXPOSE 8000

# Migrations first: Alembic is the only writer of DDL (gap O3).
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn chat_backend.main:app --host 0.0.0.0 --port 8000"]