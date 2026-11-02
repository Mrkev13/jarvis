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

The database Compose configuration and initial provisioning
procedure are not yet included in this repository.

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
