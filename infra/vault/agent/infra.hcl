# Vault Agent "vault-agent-infra" (INF-13): renders the secrets of db, minio, minio-init,
# grafana, postgres-exporter and backup, each into that service's own tmpfs volume
# (mounted at /out/<service> here, read-only at /run/vault in the service). AppRole role
# "infra", policy infra/vault/policies/infra.hcl: reads secret/data/infra/* only.
# Files that an image reads through a *_FILE variable hold the bare value, without a
# trailing newline.
# Vault's address comes from VAULT_ADDR (compose: http://vault:8200 on the Docker network).
# Logs in with AppRole. The role-id and secret-id are files that scripts/vault-init.sh
# writes from inside the vault container into this agent's own named volume, mounted
# read-only at /vault/approle. They are kept after reading, so a restarted agent can log in
# again. While Vault is sealed or unreachable the login fails and is retried with a backoff
# of 1 s to 10 s, so the agent renders within 10 s of `make` unsealing Vault.
auto_auth {
  method "approle" {
    mount_path = "auth/approle"
    min_backoff = "1s"
    max_backoff = "10s"
    config = {
      role_id_file_path                   = "/vault/approle/role-id"
      secret_id_file_path                 = "/vault/approle/secret-id"
      remove_secret_id_file_after_reading = false
    }
  }
}

# The token is renewed and replaced by the agent itself (TTL 1 h, max 4 h). No sink and no
# listener: the token never leaves this process; only the templates use it.
# When a template still cannot read its secret after the retries (Vault sealed again, a
# policy that no longer allows the path), the agent exits and Docker starts it again
# (restart: unless-stopped). The start removes only the agent's private marker
# /tmp/rendered (compose command), never the files in the services' volumes: a service may be
# reading them at that moment, and MinIO with a missing *_FILE silently starts with its
# default credentials. Each file is rewritten by an atomic rename, so once it exists it is
# never missing. Health check and `make vault-check` show the failure through the marker.
template_config {
  exit_on_retry_failure = true
}

# db: POSTGRES_PASSWORD_FILE (the postgres image reads it when it creates a new volume).
template {
  contents             = "{{ with secret \"secret/data/infra/db\" }}{{ .Data.data.password }}{{ end }}"
  destination          = "/out/db/postgres-password"
  perms                = "0444"
  error_on_missing_key = true
}

# minio: MINIO_ROOT_USER_FILE and MINIO_ROOT_PASSWORD_FILE.
template {
  contents             = "{{ with secret \"secret/data/infra/minio\" }}{{ .Data.data.root_user }}{{ end }}"
  destination          = "/out/minio/root-user"
  perms                = "0444"
  error_on_missing_key = true
}

template {
  contents             = "{{ with secret \"secret/data/infra/minio\" }}{{ .Data.data.root_password }}{{ end }}"
  destination          = "/out/minio/root-password"
  perms                = "0444"
  error_on_missing_key = true
}

# minio-init: an env file for infra/minio/init-bucket.sh (sourced by with-secrets).
template {
  source               = "/vault/agent/templates/minio-init.env.ctmpl"
  destination          = "/out/minio-init/env"
  perms                = "0444"
  error_on_missing_key = true
}

# grafana: GF_SECURITY_ADMIN_PASSWORD__FILE.
template {
  contents             = "{{ with secret \"secret/data/infra/grafana\" }}{{ .Data.data.admin_password }}{{ end }}"
  destination          = "/out/grafana/admin-password"
  perms                = "0444"
  error_on_missing_key = true
}

# postgres-exporter: DATA_SOURCE_PASS_FILE.
template {
  contents             = "{{ with secret \"secret/data/infra/postgres-exporter\" }}{{ .Data.data.password }}{{ end }}"
  destination          = "/out/postgres-exporter/password"
  perms                = "0444"
  error_on_missing_key = true
}

# backup: an env file that infra/backup/backup.sh sources itself, so `make backup`
# (docker compose exec) and `make restore` (docker compose run) get it too.
template {
  source               = "/vault/agent/templates/backup.env.ctmpl"
  destination          = "/out/backup/env"
  perms                = "0444"
  error_on_missing_key = true
}

# Readiness marker, the last template: rendered only once every path above is readable with
# this agent's token, into the agent's own file system (no secret in it, not shared). The
# start removes it, so the health check (marker and every file non-empty) is red until this
# run of the agent has read all its secrets: while Vault is sealed, or when a policy no
# longer allows a path.
template {
  contents    = "{{ with secret \"secret/data/infra/db\" }}{{ end }}{{ with secret \"secret/data/infra/minio\" }}{{ end }}{{ with secret \"secret/data/infra/grafana\" }}{{ end }}{{ with secret \"secret/data/infra/postgres-exporter\" }}{{ end }}{{ with secret \"secret/data/infra/backup\" }}{{ end }}ok"
  destination = "/tmp/rendered"
  perms       = "0444"
}
