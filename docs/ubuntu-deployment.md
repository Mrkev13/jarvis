# Standa Hub - Ubuntu Production

## Architecture
- Backend: FastAPI, Docker, port 127.0.0.1:8000
- Frontend: Next.js, Docker, port 127.0.0.1:3000
- Database: PostgreSQL 18, Docker
- Remote access: Tailscale Serve

## Server paths
- Application: /srv/standa-hub
- Persistent data: /srv/standa-hub-data
- Media: /srv/standa-hub-data/media
- Backups: /srv/standa-hub-data/backups

## Docker configuration
- Backend: backend/Dockerfile and backend/compose.yaml
- Frontend: frontend/Dockerfile and frontend/compose.yaml
- Backend secrets: backend/.env.production (not committed)
- Frontend build variable: NEXT_PUBLIC_API_URL
- PostgreSQL network: postgres_default

## Building images
From backend directory: docker compose build
From frontend directory: docker compose build

Building does not automatically restart running containers.

## Backups
- Timer: standa-hub-backup.timer
- Schedule: daily at 03:00
- Service: standa-hub-backup.service
- Script: /usr/local/lib/standa-hub/backup.sh
- Implementation: backend backup_service.run_backup()

## Restoration
1. Preserve current database and media.
2. Select a verified backup.
3. Restore into an isolated test database.
4. Validate tables and application compatibility.
5. Schedule production restoration separately.

## Monitoring
- Uptime Kuma
- server-monitor.timer
- Docker restart policy: unless-stopped

## Security
- HTTP services bind to localhost.
- Remote access uses Tailscale.
- Never commit secrets or production .env files.

## Pending work
- Document PostgreSQL provisioning.
- Document Tailscale Serve setup.
- Validate complete recovery on a separate environment.
- Implement Linux auto-deploy separately.

## PostgreSQL production configuration

- Docker image: postgres:18.6
- Container: standa-postgres
- Docker network: postgres_default
- Persistent volume: postgres_postgres_data
- Volume mount: /var/lib/postgresql
- Restart policy: unless-stopped

The database must be provisioned before starting the backend.
Database credentials belong in private environment configuration.
Do not delete or recreate the production volume during deployment.

The PostgreSQL Compose configuration is included in
postgres/compose.yaml. Provisioning requires a private
postgres/.env file containing the database password.

## Tailscale Serve configuration

Frontend:
https://standa-server.tail068a4b.ts.net
proxies to http://127.0.0.1:3000

Backend:
https://standa-server.tail068a4b.ts.net:8443
proxies to http://127.0.0.1:8000

Both endpoints are accessible only within the tailnet.

Tailscale authentication and Serve configuration must be
restored separately when rebuilding the server.

## PostgreSQL provisioning

The repository contains postgres/compose.yaml.

For a new installation:
1. Copy postgres/.env.example to postgres/.env.
2. Replace the example password with a strong unique password.
3. Start PostgreSQL from the postgres directory.
4. Verify PostgreSQL health before starting the backend.
5. Configure the backend database connection privately.

The Compose project must be named postgres so that
the backend can reach the postgres_default network.

The postgres_postgres_data volume contains persistent database data.
Never remove it during application updates.

The backend and frontend are separate Compose projects.
Start PostgreSQL before the backend.

## Tailscale

Install and authenticate Tailscale separately.
Configure Serve to proxy:
- HTTPS port 443 to localhost:3000
- HTTPS port 8443 to localhost:8000

Restrict access to the tailnet.

## Verified installation tests (2026-11-02)

The MRK-101 deployment files were tested on the Ubuntu host
without replacing or restarting the production containers.

- Backend Docker image: build successful.
- Frontend Docker image: build successful.
- Frontend /login: HTTP 200 on isolated port 3100.
- Temporary PostgreSQL 18.6: started on isolated Docker network.
- Alembic upgrade head: successful.
- Database schema: 51 tables, revision 0027_ui_preferences.
- Backend /health: HTTP 200, status healthy.
- Database: reachable.
- Migrations: current.
- Scheduler and backup jobs: disabled during test.
- Temporary test containers and Docker network: removed.

These tests verify fresh database initialization and HTTP startup.
They do not constitute a full disaster-recovery test from backup.

## Disaster recovery limitations

The following components require restoration or separate configuration:

- Production PostgreSQL data and credentials.
- Persistent application media.
- Production backend environment configuration.
- Tailscale authentication and Serve configuration.
- Systemd backup and monitoring units.
- Scheduled Windows off-machine backup synchronization.

Never overwrite an existing production database during a restore test.
Restore a verified backup into an isolated database first.

## Backup integrity verification (2026-11-02)

The automatic backup from 2026-11-02 03:00 CET was checked:

- Backup run status: success.
- PostgreSQL gzip archive: integrity check passed.
- PostgreSQL archive SHA-256: matched the backup run manifest.
- Media manifest SHA-256: matched the backup run manifest.
- Media files: 75 of 75 verified by size and SHA-256.
- Missing or corrupted media files: 0.
- Verified media size: 54,798,363 bytes.

The media manifest's archive_path values are relative to the
backup root (/srv/standa-hub-data/backups), not its media subdirectory.

These results establish backup-file integrity. They do not prove
a complete application restore on a replacement Ubuntu host.


## Ubuntu recovery procedure

Use this procedure only on a replacement server or an isolated
recovery environment. Never run it against the live production database.

1. Install Ubuntu Server, Docker Engine, Docker Compose and Tailscale.
2. Clone the reviewed application revision into /srv/standa-hub.
3. Restore private environment files from secure storage.
4. Create /srv/standa-hub-data/media and backups directories.
5. Restore a verified backup set into the backups directory.
6. Start PostgreSQL using the postgres Compose project.
7. Create a separate empty recovery database.
8. Restore the PostgreSQL dump into that database.
9. Verify Alembic revision, table count and application compatibility.
10. Restore media files into a separate recovery directory.
11. Verify every restored file against its manifest SHA-256 and size.
12. Configure the backend to use the restored database and media.
13. Start backend with scheduler, delivery and backup jobs disabled.
14. Verify /health and application data before enabling scheduled jobs.
15. Start frontend, configure Tailscale Serve and monitoring.
16. Enable scheduled jobs only after validation and confirming
    exactly one scheduler owner.

The PostgreSQL dump is compressed SQL. Restore with psql,
not pg_restore. Use gzip -dc to decompress the archive.

The media manifest's archive_path is relative to BACKUP_DIR.
Restore each file to MEDIA_DIR / relative_path.

See [Backup and restore](backups.md) for integrity requirements,
rollback principles and the historical recovery drills.

A complete replacement-host recovery remains untested.

## Docker environment configuration

Never commit backend/.env.production or postgres/.env.

### PostgreSQL

1. Copy postgres/.env.example to postgres/.env.
2. Set a strong unique POSTGRES_PASSWORD.
3. Restrict file permissions to the deployment account.
4. Keep the PostgreSQL Compose project name as postgres.

### Backend

1. Copy backend/.env.docker.example to backend/.env.production.
2. Replace DATABASE_URL with the correct PostgreSQL credentials.
   The hostname inside Docker is standa-postgres, not localhost.
   URL-encode special characters in the database password.
3. Generate a valid bcrypt AUTH_PIN_HASH.
4. Configure a real GROQ_API_KEY or OPENAI_API_KEY.
5. Keep MEDIA_DIR=/data/media and BACKUP_DIR=/data/backups.
6. Keep RUN_ALEMBIC_UPGRADE_AT_STARTUP=false.
7. Keep scheduler, delivery and backup jobs disabled during recovery.
8. Set AUTH_COOKIE_SECURE=true when using Tailscale HTTPS.
9. Protect the file using chmod 600.

Validate configuration using the backend Docker image:

    cd backend
    docker compose build backend
    docker compose run --rm --no-deps --entrypoint python backend -c 'import os; from production import validate_environment; validate_environment(os.environ); print("Production configuration valid")'

This checks production settings without starting Uvicorn or running
database migrations. It does not require backend Python packages
on the Ubuntu host.

Do not print or commit validated environment values.

### Frontend

Copy frontend/.env.example to frontend/.env and replace
NEXT_PUBLIC_API_URL with the actual HTTPS backend URL.

For this installation:

    NEXT_PUBLIC_API_URL=https://standa-server.tail068a4b.ts.net:8443

This variable is read by Docker Compose for both the frontend build
and runtime configuration.

### Compose validation

Run docker compose config --quiet separately from the backend,
frontend and postgres directories before starting any service.

Configuration validation does not start containers or modify databases.

## Systemd backup installation

Ubuntu production uses one backup owner: standa-hub-backup.timer.

The application's internal backup scheduler must remain disabled:
BACKUP_ENABLED=false.

The timer invokes a separate process inside the running backend
container and enables backup execution only for that process.

### Install

Run from the repository root:

    sudo install -d -m 755 /usr/local/lib/standa-hub

    sudo install -m 755 deploy/scripts/backup.sh /usr/local/lib/standa-hub/backup.sh

    sudo install -m 644 deploy/systemd/standa-hub-backup.service /etc/systemd/system/

    sudo install -m 644 deploy/systemd/standa-hub-backup.timer /etc/systemd/system/

    sudo systemctl daemon-reload

    sudo systemctl enable --now standa-hub-backup.timer

### Verify

    systemctl list-timers standa-hub-backup.timer

    systemctl status standa-hub-backup.timer

    journalctl -u standa-hub-backup.service -n 50 --no-pager

The timer runs daily at 03:00 server local time.

The backend container must be running and connected to PostgreSQL.
BACKUP_DIR must point to /data/backups inside the container.

Do not enable the application's internal backup scheduling alongside
the systemd timer.

On a replacement server, install the timer only after validating
the restored database, media, backend configuration and backup path.

Before the first scheduled run, validate the service explicitly:

    sudo systemctl start standa-hub-backup.service

    sudo systemctl status standa-hub-backup.service

A successful systemd exit must correspond to a successful BackupLog
record and a verified backup manifest.
