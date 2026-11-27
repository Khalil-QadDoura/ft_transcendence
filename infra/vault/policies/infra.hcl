# Policy "infra" (INF-13): the token of vault-agent-infra reads the secrets of the
# infrastructure services (db, minio, grafana, postgres-exporter, backup) and nothing else.
# KV v2 is mounted at secret/: a read of secret/infra/<service> is a read of
# secret/data/infra/<service>. No list, no write, no other path.
path "secret/data/infra/*" {
  capabilities = ["read"]
}
