# backup service (INF-14): no new external image. The db image provides pg_dump and
# pg_restore of the server's own major version (15) and bash with coreutils; the MinIO
# image provides the mc client (/usr/bin/mcli, a static binary; /usr/bin/mc links to it).
# Both FROM lines carry the exact tag and digest of docker-compose.yml (x-minio-image and
# the db service); bump them together. `make images-check` reads both.
FROM pgsty/minio:RELEASE.2026-08-04T00-00-00Z@sha256:b6bfe7239bfc83fb90d31612d9704d86039dd714f7904b3f1ad68f211e602372 AS mc

FROM imresamu/postgis:15-3.4@sha256:44d4443d107a7750ea29a441dec0050cd7543178f011ae0620e4b572578e9300

COPY --from=mc /usr/bin/mcli /usr/local/bin/mc

# A user of its own (uid 10002, next to the api's 10001); /backups belongs to it, so a new
# `backups` volume starts with that owner (Docker copies the ownership of the image's
# directory into an empty named volume).
RUN groupadd --system --gid 10002 dumper \
    && useradd --system --uid 10002 --gid 10002 --home-dir /nonexistent --no-create-home \
        --shell /usr/sbin/nologin dumper \
    && mkdir -p /backups/db /backups/files \
    && chown -R 10002:10002 /backups

COPY --chmod=0755 backup.sh /usr/local/bin/backup.sh

USER 10002:10002
WORKDIR /backups
# Replaces the image's docker-entrypoint.sh, which would start a PostgreSQL server.
ENTRYPOINT ["/usr/local/bin/backup.sh"]
CMD ["loop"]
