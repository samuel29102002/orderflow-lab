-- Enable TimescaleDB for hypertables on events/snapshots/pnl_curve.
-- See PROJECT_DESIGN.md Phase 3 — Database.
CREATE EXTENSION IF NOT EXISTS timescaledb;
CREATE EXTENSION IF NOT EXISTS citext;
