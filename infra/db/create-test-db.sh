#!/bin/sh
# Creates the test database (POSTGRES_TEST_DB) next to the app database: owned by
# POSTGRES_USER, with PostGIS, which the schema needs (jobs.location_point). The backend
# tests use only this database (TEST_DATABASE_URL); they delete what they find.
#
# Runs in the db container, from two places:
#   - the image's entrypoint, once, when the db-data volume is new
#     (mounted as /docker-entrypoint-initdb.d/20-create-test-db.sh, after 10_postgis.sh);
#   - `make test`, on every run, for a volume that already existed before this script.
# Idempotent: when the database is there, it changes nothing. Names come from the
# container environment; it connects over the local socket, so it needs no password.
set -eu

: "${POSTGRES_USER:?}" "${POSTGRES_DB:?}" "${POSTGRES_TEST_DB:?}"

# Never the app database; and "test" in the name, or backend/tests/conftest.py skips it.
case $POSTGRES_TEST_DB in
	"$POSTGRES_DB")
		echo "POSTGRES_TEST_DB must not be the app database ($POSTGRES_DB)" >&2
		exit 1 ;;
	*test*) ;;
	*)
		echo "POSTGRES_TEST_DB=$POSTGRES_TEST_DB must contain \"test\"" >&2
		exit 1 ;;
esac

# There is no CREATE DATABASE IF NOT EXISTS; psql's \if does the check.
psql -v ON_ERROR_STOP=1 --no-psqlrc --quiet --username="$POSTGRES_USER" --dbname=postgres \
	--set=db="$POSTGRES_TEST_DB" --set=owner="$POSTGRES_USER" <<'SQL'
SELECT NOT EXISTS (SELECT FROM pg_database WHERE datname = :'db') AS missing \gset
\if :missing
  \echo Creating the test database :db
  CREATE DATABASE :"db" OWNER :"owner";
\else
  \echo Test database :db is already there
\endif
SQL

psql -v ON_ERROR_STOP=1 --no-psqlrc --quiet --username="$POSTGRES_USER" \
	--dbname="$POSTGRES_TEST_DB" <<'SQL'
SET client_min_messages = warning;
CREATE EXTENSION IF NOT EXISTS postgis;
SQL
