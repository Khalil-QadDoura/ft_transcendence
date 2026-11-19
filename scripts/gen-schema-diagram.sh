#!/usr/bin/env bash
# make schema-diagram (BE-14): draws docs/db/schema.svg, the database picture in the README,
# from a real database built by our Alembic migrations, so it never drifts from the schema.
# 1. builds the backend image (backend/Dockerfile, stage runtime) and a small drawing image
#    (eralchemy and Graphviz, versions pinned below);
# 2. starts a throwaway PostgreSQL + PostGIS from the db image of docker-compose.yml, on a
#    private Docker network of its own (no port published on this machine);
# 3. runs `alembic upgrade head` in the backend image against it;
# 4. runs scripts/gen-schema-diagram.py in the drawing image: eralchemy reads the tables
#    back from that database and Graphviz draws them as an SVG;
# 5. removes the container, the network and the two image names it made, also on failure.
# Needs only Docker and bash. No .env, no secret: the throwaway database gets made-up values.
# Never touches the running stack (no compose, names of its own). Run it after a migration
# changes the schema, and commit the new picture.
set -euo pipefail

cd "$(dirname "$0")/.."

OUTPUT=docs/db/schema.svg
# Each run names what it makes <prefix>-<process id>, so two runs never clash.
NAME="${SCHEMA_DIAGRAM_PREFIX:-schema-diagram}-$$"
NETWORK="$NAME-net"
DB_CONTAINER="$NAME-db"
BACKEND_IMAGE="$NAME-backend"
DRAW_IMAGE="$NAME-draw"
# Made-up values for the throwaway database and the settings Alembic loads; nothing outside
# this run uses them.
DB_USER=diagram
DB_PASSWORD=diagram
DB_NAME=diagram
JWT_SECRET=schema-diagram-throwaway-value-not-a-secret

# The drawing image: the same Python base as backend/Dockerfile (tag and digest, INF-07),
# Graphviz from Debian and the Python packages from PyPI, each at a fixed version, so two
# runs on the same schema write the same file.
PYTHON_IMAGE=python:3.11-slim@sha256:07d4824036af339fa1b6ef769cc99d9c10a141769538b52b3b597c84f7a7b535
GRAPHVIZ_VERSION=2.42.4-3
ERALCHEMY_VERSION=1.7.0
GRAPHVIZ_PY_VERSION=0.21
SQLALCHEMY_VERSION=2.0.55
PSYCOPG2_VERSION=2.9.13
GEOALCHEMY2_VERSION=0.21.0

TMP="$(mktemp -d)"

# fail MESSAGE [LOG]: says why it stopped (and prints the end of LOG), then exits 1.
fail() {
	echo "gen-schema-diagram: $1" >&2
	if [[ -n "${2:-}" && -s "$2" ]]; then
		echo "--- last lines of its output ---" >&2
		tail -n 30 "$2" >&2
	fi
	exit 1
}

cleanup() {
	docker rm --force "$DB_CONTAINER" >/dev/null 2>&1 || true
	docker network rm "$NETWORK" >/dev/null 2>&1 || true
	# Removes these two names only; an image that another name also points at stays.
	docker image rm "$BACKEND_IMAGE" "$DRAW_IMAGE" >/dev/null 2>&1 || true
	rm -rf "$TMP"
}
trap cleanup EXIT

command -v docker >/dev/null \
	|| fail "Docker is required and was not found (install Docker Engine 25+ or Docker Desktop)"
docker info >/dev/null 2>&1 \
	|| fail "Docker is installed but not running (start Docker Desktop or the docker service)"

# The image line of the db service in docker-compose.yml: the throwaway database is the
# same PostgreSQL + PostGIS as the stack's.
DB_IMAGE="$(awk '
	/^  db:/ { in_db = 1; next }
	in_db && /^  [^ ]/ { exit }
	in_db && /^    image:/ { print $2; exit }' docker-compose.yml)"
[[ -n "$DB_IMAGE" ]] || fail "no image found for the db service in docker-compose.yml"

# Graphviz's text plugin (pango) measures each letter rounded to whole pixels, a little
# narrower than browsers draw the same text, so words ran into each other there. Without
# it, Graphviz uses Helvetica's published letter widths, the ones browsers use; `dot -c`
# updates its list of plugins. No font is needed then: the SVG names the font, the browser
# draws it.
cat >"$TMP/draw.Dockerfile" <<EOF
FROM $PYTHON_IMAGE
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1 PYTHONDONTWRITEBYTECODE=1
RUN apt-get update \\
 && apt-get install -y --no-install-recommends graphviz=$GRAPHVIZ_VERSION \\
 && rm -rf /var/lib/apt/lists/* \\
 && rm /usr/lib/*/graphviz/libgvplugin_pango.so* \\
 && dot -c
RUN pip install eralchemy==$ERALCHEMY_VERSION graphviz==$GRAPHVIZ_PY_VERSION \\
    SQLAlchemy==$SQLALCHEMY_VERSION psycopg2-binary==$PSYCOPG2_VERSION \\
    GeoAlchemy2==$GEOALCHEMY2_VERSION
USER nobody
EOF

echo "gen-schema-diagram: building the backend image (backend/Dockerfile)"
docker build --quiet --target runtime --tag "$BACKEND_IMAGE" backend >"$TMP/build.log" 2>&1 \
	|| fail "could not build the backend image" "$TMP/build.log"

echo "gen-schema-diagram: building the drawing image (eralchemy $ERALCHEMY_VERSION, Graphviz $GRAPHVIZ_VERSION)"
docker build --quiet --tag "$DRAW_IMAGE" - <"$TMP/draw.Dockerfile" >"$TMP/build.log" 2>&1 \
	|| fail "could not build the drawing image (is every version pinned in this script still available?)" "$TMP/build.log"

echo "gen-schema-diagram: starting a throwaway database ($DB_IMAGE)"
docker network create --internal "$NETWORK" >"$TMP/db.log" 2>&1 \
	|| fail "could not create the Docker network $NETWORK" "$TMP/db.log"
docker run --detach --name "$DB_CONTAINER" --network "$NETWORK" \
	-e POSTGRES_USER="$DB_USER" -e POSTGRES_PASSWORD="$DB_PASSWORD" -e POSTGRES_DB="$DB_NAME" \
	"$DB_IMAGE" >"$TMP/db.log" 2>&1 \
	|| fail "could not start the database container" "$TMP/db.log"
# Ready once it answers over TCP: the image's first-start setup (PostGIS) uses a socket only.
ready=no
for _ in $(seq 1 90); do
	if docker exec "$DB_CONTAINER" pg_isready -q -h 127.0.0.1 -U "$DB_USER" -d "$DB_NAME" 2>/dev/null; then
		ready=yes
		break
	fi
	sleep 1
done
if [[ "$ready" != yes ]]; then
	docker logs "$DB_CONTAINER" >"$TMP/db.log" 2>&1 || true
	fail "the database was not ready after 90 seconds" "$TMP/db.log"
fi

echo "gen-schema-diagram: running the migrations (alembic upgrade head)"
docker run --rm --network "$NETWORK" \
	-e DATABASE_URL="postgresql+asyncpg://$DB_USER:$DB_PASSWORD@$DB_CONTAINER:5432/$DB_NAME" \
	-e JWT_SECRET="$JWT_SECRET" \
	"$BACKEND_IMAGE" alembic upgrade head >"$TMP/migrate.log" 2>&1 \
	|| fail "the migrations failed" "$TMP/migrate.log"

echo "gen-schema-diagram: drawing the tables (eralchemy and Graphviz)"
# The PostGIS image also puts its tiger and topology schemas (a geocoder's tables) on the
# search path; this connection searches the public schema only, where our tables are.
docker run --rm --interactive --network "$NETWORK" \
	-e DATABASE_URL="postgresql://$DB_USER:$DB_PASSWORD@$DB_CONTAINER:5432/$DB_NAME?options=-csearch_path%3Dpublic" \
	"$DRAW_IMAGE" python - <scripts/gen-schema-diagram.py >"$TMP/schema.svg" 2>"$TMP/draw.log" \
	|| fail "drawing failed" "$TMP/draw.log"
grep -q '<svg' "$TMP/schema.svg" || fail "the drawing is not an SVG file" "$TMP/draw.log"

mkdir -p "$(dirname "$OUTPUT")"
mv "$TMP/schema.svg" "$OUTPUT"
echo "gen-schema-diagram: wrote $OUTPUT ($(grep -c 'class="node"' "$OUTPUT") tables)"
