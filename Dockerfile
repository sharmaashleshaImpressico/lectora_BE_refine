# Lectora backend — same image for dev (docker-compose.yml) and prod
# (docker-compose.prod.yml); prod overrides CMD with --workers.
FROM python:3.12-slim

WORKDIR /app

# pyodbc + python-docx/lxml build deps + LibreOffice for DOCX→PDF conversion
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        curl \
        gnupg2 \
        unixodbc \
        unixodbc-dev \
        gcc \
        g++ \
        libxml2-dev \
        libxslt1-dev \
        libreoffice-writer \
    && curl -fsSL https://packages.microsoft.com/keys/microsoft.asc \
        | gpg --dearmor -o /usr/share/keyrings/microsoft-prod.gpg \
    && echo "deb [arch=amd64 signed-by=/usr/share/keyrings/microsoft-prod.gpg] https://packages.microsoft.com/debian/12/prod bookworm main" \
        > /etc/apt/sources.list.d/mssql-release.list \
    && apt-get update \
    && ACCEPT_EULA=Y apt-get install -y --no-install-recommends msodbcsql18 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY alembic.ini .
COPY app/ app/

COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENV PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

EXPOSE 8000

ENTRYPOINT ["/entrypoint.sh"]

# Single FastAPI app (API + in-process Service Bus worker thread started in
# app.main's lifespan — there is no separate worker module/process).
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--log-level", "info"]
