#!/usr/bin/env bash
# make secrets-check (BE-13): looks for secrets (keys, passwords, tokens) in every commit of
# every branch of this repository, with gitleaks in a container (pinned by tag and digest).
# Scans a fresh mirror clone, so it reads only what Git holds: never .env or another ignored
# file. Prints the findings with their values replaced by REDACTED and exits 1 if there is
# one. .gitleaksignore lists the findings checked by hand and known not to be secrets.
# Needs only Docker and git; no .env, no running stack.
set -euo pipefail

cd "$(dirname "$0")/.."

GITLEAKS_IMAGE="ghcr.io/gitleaks/gitleaks:v8.30.1@sha256:c00b6bd0aeb3071cbcb79009cb16a60dd9e0a7c60e2be9ab65d25e6bc8abbb7f"

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

# Every branch and tag this clone knows, as Git stores them; no working files.
git clone --quiet --mirror "$(git rev-parse --show-toplevel)" "$work/repo.git"
cp .gitleaksignore "$work/.gitleaksignore"

echo "secrets-check: $(git -C "$work/repo.git" rev-list --all | wc -l | tr -d ' ') commits, every branch"
docker run --rm -v "$work:/scan:ro" "$GITLEAKS_IMAGE" \
	git /scan/repo.git --log-opts=--all --redact --no-banner --verbose \
	--gitleaks-ignore-path /scan/.gitleaksignore
echo "secrets-check: no secret found"
