# Policy "api" (INF-12): the API's AppRole token reads its own secrets and nothing else.
# KV v2 is mounted at secret/: a read of secret/api/<name> is a read of
# secret/data/api/<name>. No list, no write, no other path.
path "secret/data/api/*" {
  capabilities = ["read"]
}
