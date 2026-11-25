# Vault Agent "vault-agent-worker" (INF-13): renders the secrets of the worker into the
# tmpfs volume secrets-worker (mounted at /out/worker here, read-only at /run/vault in the
# worker). AppRole role "worker", policy infra/vault/policies/worker.hcl: reads
# secret/data/worker/* only.
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

template {
  source               = "/vault/agent/templates/worker.env.ctmpl"
  destination          = "/out/worker/env"
  perms                = "0444"
  error_on_missing_key = true
}

# Readiness marker, the last template: rendered only once every path above is readable with
# this agent's token, into the agent's own file system (no secret in it, not shared). The
# start removes it, so the health check (marker and every file non-empty) is red until this
# run of the agent has read all its secrets: while Vault is sealed, or when a policy no
# longer allows a path.
template {
  contents    = "{{ with secret \"secret/data/worker/jwt\" }}{{ end }}{{ with secret \"secret/data/worker/db\" }}{{ end }}{{ with secret \"secret/data/worker/minio\" }}{{ end }}{{ with secret \"secret/data/worker/openai\" }}{{ end }}ok"
  destination = "/tmp/rendered"
  perms       = "0444"
}
