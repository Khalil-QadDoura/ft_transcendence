# Vault server configuration (INF-12, module M13), mounted read-only at
# /vault/config/vault.hcl. Server mode, never dev mode: data stays on disk and Vault
# starts sealed after every restart; scripts/vault-init.sh, run by `make`, initializes
# and unseals it. Details: docs/infra/vault.md.

# File storage on the named volume vault-data (single node). Everything Vault writes
# there is encrypted; only an unsealed Vault holds the key in memory.
storage "file" {
  path = "/vault/file"
}

# Plain HTTP, on the internal Docker network only: no host port and no proxy route.
listener "tcp" {
  address     = "0.0.0.0:8200"
  tls_disable = true
}

# How other containers reach this node.
api_addr = "http://vault:8200"

# No web UI; the CLI inside the container is the only client.
ui = false

# mlock stays on (no disable_mlock): keys and secrets in memory are never swapped to
# disk. Vault runs as a non-root user, so it can lock its memory only because
# docker-compose.yml raises the container's memlock limit to unlimited; cap_add IPC_LOCK
# is kept there too, but the Vault 2.x binary carries no file capability to use it.

log_format = "json"
