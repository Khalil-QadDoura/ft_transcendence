#!/usr/bin/env bash
# Generates the self-signed localhost certificate for the front proxy into
# infra/proxy/certs/ (git-ignored). Keeps an existing pair unless --force is given.
set -euo pipefail

CERT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/certs"
CRT="$CERT_DIR/server.crt"
KEY="$CERT_DIR/server.key"
# Longest lifetime browsers accept for a TLS certificate.
DAYS=825

case "${1:-}" in
    "") force=0 ;;
    --force) force=1 ;;
    *)
        echo "usage: $(basename "$0") [--force]" >&2
        exit 2
        ;;
esac

if [ "$force" -eq 0 ] && [ -s "$CRT" ] && [ -s "$KEY" ]; then
    echo "gen-cert: keeping existing certificate in $CERT_DIR (--force replaces it)"
    exit 0
fi

mkdir -p "$CERT_DIR"
WORK_DIR="$(mktemp -d "$CERT_DIR/.tmp.XXXXXX")"
trap 'rm -rf "$WORK_DIR"' EXIT

cat > "$WORK_DIR/openssl.cnf" <<'EOF'
[req]
prompt = no
distinguished_name = dn
x509_extensions = v3

[dn]
CN = localhost

[v3]
basicConstraints = critical, CA:FALSE
keyUsage = critical, digitalSignature, keyEncipherment
extendedKeyUsage = serverAuth
subjectAltName = DNS:localhost, IP:127.0.0.1
EOF

openssl req -x509 -newkey rsa:2048 -nodes -sha256 -days "$DAYS" \
    -config "$WORK_DIR/openssl.cnf" \
    -keyout "$WORK_DIR/server.key" \
    -out "$WORK_DIR/server.crt" 2>/dev/null

# World-readable on purpose: the container reads this bind mount as its unprivileged
# nginx user (uid 101), not as the host user. The key is only ever valid for localhost.
chmod 644 "$WORK_DIR/server.crt" "$WORK_DIR/server.key"
mv -f "$WORK_DIR/server.key" "$KEY"
mv -f "$WORK_DIR/server.crt" "$CRT"

echo "gen-cert: wrote $CRT and $KEY"
openssl x509 -in "$CRT" -noout -subject -enddate
