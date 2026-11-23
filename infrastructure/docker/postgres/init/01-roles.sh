#!/bin/sh
# Runs once, when the Postgres data volume is first initialized.
# Creates the non-owner application role (subject to row-level security) and a
# read-only role for development inspection. Table privileges are granted by migrations.
set -eu

: "${VERITAS_APP_DB_USER:?VERITAS_APP_DB_USER is required}"
: "${VERITAS_APP_DB_PASSWORD:?VERITAS_APP_DB_PASSWORD is required}"
: "${VERITAS_RO_DB_USER:?VERITAS_RO_DB_USER is required}"
: "${VERITAS_RO_DB_PASSWORD:?VERITAS_RO_DB_PASSWORD is required}"

psql -v ON_ERROR_STOP=1 \
  --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
  -v app_user="$VERITAS_APP_DB_USER" -v app_pw="$VERITAS_APP_DB_PASSWORD" \
  -v ro_user="$VERITAS_RO_DB_USER" -v ro_pw="$VERITAS_RO_DB_PASSWORD" <<'SQL'
CREATE ROLE :"app_user" LOGIN PASSWORD :'app_pw' NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE;
CREATE ROLE :"ro_user" LOGIN PASSWORD :'ro_pw' NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE;
SQL
