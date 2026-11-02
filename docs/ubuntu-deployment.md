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

## Tailscale Serve recovery commands

Validated against Tailscale 1.104.4 on 2026-11-02.

Production uses Tailscale Serve, not Funnel.
Both HTTPS endpoints must remain tailnet-only.

### Provision a replacement Ubuntu server

1. Install Tailscale and authenticate the replacement machine.
2. Verify that the machine is connected to the correct tailnet.
3. Start the restored backend and frontend containers.
4. Confirm local HTTP endpoints work before enabling Serve.

Verify local endpoints:

    curl -f http://127.0.0.1:3000/login
    curl -f http://127.0.0.1:8000/health

Configure persistent HTTPS proxies:

    sudo tailscale serve --bg --https=443 http://127.0.0.1:3000

    sudo tailscale serve --bg --https=8443 http://127.0.0.1:8000

Verify configuration:

    sudo tailscale serve status
    sudo tailscale funnel status

Expected mappings:

- HTTPS 443 -> http://127.0.0.1:3000
- HTTPS 8443 -> http://127.0.0.1:8000
- Both endpoints must display "tailnet only".
- No endpoint may display "Available on the internet".

Verify access from another authorized tailnet device.
Check tailnet grants/ACLs in the Tailscale admin console.
Serve is not a substitute for application authentication.

### Disable individual proxies

    sudo tailscale serve --https=443 off
    sudo tailscale serve --https=8443 off

### Emergency reset

    sudo tailscale serve reset

WARNING: Reset removes the device's Serve configuration.
Never execute reset on the working production server merely
to test recovery instructions.

After reset, restore the two mappings using --bg commands above.

The replacement machine may receive a different MagicDNS hostname.
Update FRONTEND_ORIGINS, NEXT_PUBLIC_API_URL and relevant
authentication/cookie settings before accepting users.

Tailscale authentication state and tailnet access policies are
not stored in the application repository.

## Verified PostgreSQL and media recovery drill

Tested on 2026-11-02 using the automatic backup from 03:00 CET.

The recovery scripts are:
- deploy/scripts/restore-postgres-test.sh
- deploy/scripts/restore-media.py

### Restore prerequisites

Use a disposable PostgreSQL 18.6 container with:
- Name: jarvis-mrk101-restore
- Database: standa_hub_restore
- User: standa_hub
- Temporary database storage, never a production volume
- No published ports
- No connection to postgres_default

Use the exact backup run manifest and its associated media manifest.

### PostgreSQL recovery

The PostgreSQL restore script validates:
- Backup run status
- Archive SHA-256 and size
- Docker container identity
- Temporary storage and network isolation
- Database user and database name

It restores the plain SQL dump using psql with ON_ERROR_STOP
and a single transaction.

Example, after creating the disposable database container:

    ./deploy/scripts/restore-postgres-test.sh \
      /srv/standa-hub-data/backups \
      /srv/standa-hub-data/backups/runs/backup_20261102_020002_673211.json \
      jarvis-mrk101-restore

Expected result: DATABASE_RESTORE_OK.

### Media recovery

Restore media only into a new empty directory:

    sudo python3 deploy/scripts/restore-media.py \
      --backup-root /srv/standa-hub-data/backups \
      --run-manifest /srv/standa-hub-data/backups/runs/backup_20261102_020002_673211.json \
      --manifest /srv/standa-hub-data/backups/media/manifests/media_20261102_020002_673211.json \
      --destination /tmp/jarvis-mrk101-media-restore

The script checks the media manifest checksum, individual file
sizes and SHA-256 values, and refuses an existing destination.

### Verified results

- PostgreSQL restore: successful
- Database tables: 51
- Alembic revision: 0027_ui_preferences
- Media files: 75/75 restored and verified
- Media bytes: 54,798,363
- Backend started over restored database and read-only media
- Backend /health: HTTP 200, healthy
- Scheduler, delivery and backups: disabled during test

The integration test used APP_ENV=development and a dummy API key.
It does not prove production deployment on a replacement host.

### Production cutover and rollback

A production cutover must be performed during a maintenance window.

1. Confirm a recent verified backup and a separate off-machine copy.
2. Stop application traffic and scheduled jobs.
3. Preserve the existing database and media as rollback sources.
4. Restore into separate database and media locations.
5. Validate the restored schema, data, media and backend.
6. Switch the application configuration only after validation.
7. Start exactly one backend scheduler owner.
8. Verify application health and critical user workflows.
9. Keep previous data intact until the new installation has
   completed successful backups and sustained monitoring.

Rollback requires stopping the replacement application, restoring
the original database and media configuration, and verifying health.

Never delete or overwrite the previous database or media as part
of the initial cutover. Never use the isolated restore-test script
directly against production PostgreSQL.

Exact production cutover commands are environment-specific and
must be reviewed before execution.
