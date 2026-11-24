# Policy "worker" (INF-12): the moderation worker's AppRole token reads its own secrets
# and nothing else. KV v2 is mounted at secret/: a read of secret/worker/<name> is a read
# of secret/data/worker/<name>. No list, no write, no other path.
path "secret/data/worker/*" {
  capabilities = ["read"]
}
