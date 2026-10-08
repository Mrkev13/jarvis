FROM python:3.12-slim-trixie
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
# PostgreSQL client 17 can dump the PostgreSQL 16 service.
RUN apt-get update && apt-get install -y --no-install-recommends postgresql-client && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN --mount=type=secret,id=build_ca \
    if [ -f /run/secrets/build_ca ]; then export PIP_CERT=/run/secrets/build_ca; fi; \
    pip install --no-cache-dir -r requirements.txt
COPY --chown=10001:10001 . .
RUN useradd --uid 10001 --create-home hub && mkdir -p /data/media /data/backups && chown -R hub:hub /data
USER hub
EXPOSE 8000
CMD ["python", "production.py", "--host", "0.0.0.0", "--port", "8000"]
