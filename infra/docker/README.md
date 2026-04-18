# infra/docker

Local dev infrastructure.

## Services

| Service  | Image                               | Host port |
|----------|-------------------------------------|-----------|
| postgres | `timescale/timescaledb:latest-pg16` | 5432      |
| redis    | `redis:7-alpine`                    | 6379      |

TimescaleDB + `citext` extensions are enabled on first boot via `initdb/01-extensions.sql`.

## Usage

```bash
# Copy defaults (optional — compose has sensible fallbacks)
cp .env.example .env

# From repo root:
docker compose -f infra/docker/docker-compose.yml up -d

# Tail logs
docker compose -f infra/docker/docker-compose.yml logs -f

# Teardown (keeps volumes)
docker compose -f infra/docker/docker-compose.yml down

# Full wipe (drops volumes)
docker compose -f infra/docker/docker-compose.yml down -v
```

Default credentials (dev only): `orderflow` / `orderflow` / db `orderflow`.
