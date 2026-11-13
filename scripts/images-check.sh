#!/usr/bin/env bash
# make images-check (INF-07): every image the stack pulls must be pinned by an explicit tag
# and a digest, `name:tag@sha256:<64 hex>`, and the tag must not be `latest`.
# Checks the `image:` of every compose service (all profiles, YAML anchors resolved) and
# every FROM in the repository's Dockerfiles; a FROM that names an earlier stage of the same
# Dockerfile (or `scratch`) is not an image and is skipped. Prints each offender, exits 1
# if there is one. Needs only Docker (compose v2), bash and awk; no .env.
set -euo pipefail

cd "$(dirname "$0")/.."

# Prints nothing when the reference is pinned, else the reason.
problem() {
	local ref="$1" name tag
	if [[ ! "$ref" =~ ^[^@[:space:]]+@sha256:[0-9a-f]{64}$ ]]; then
		echo "no @sha256 digest"
		return
	fi
	name="${ref%%@*}"
	# A colon after the last slash starts the tag; one before it is a registry port.
	if [[ "${name##*/}" != *:* ]]; then
		echo "no explicit tag"
		return
	fi
	tag="${name##*:}"
	if [[ "$tag" == latest ]]; then
		echo "tag latest"
	fi
}

failed=0
checked=0

report() {
	local where="$1" ref="$2" why
	checked=$((checked + 1))
	why="$(problem "$ref")"
	if [[ -n "$why" ]]; then
		echo "FAIL  $where: $ref ($why)"
		failed=$((failed + 1))
	else
		local digest="${ref#*@sha256:}"
		echo "ok    $where: ${ref%%@*}@sha256:${digest:0:12}…"
	fi
}

# Compose: `config` prints the merged model; services sit at two spaces, their keys at four.
# --no-interpolate keeps ${VARS} as written, so no .env is needed.
config="$(docker compose --profile '*' config --no-interpolate)"
while IFS=$'\t' read -r service ref; do
	report "docker-compose.yml service $service" "$ref"
done < <(printf '%s\n' "$config" | awk '
	/^[^ ]/ { in_services = ($0 == "services:"); next }
	in_services && /^  [^ #][^:]*:[ ]*$/ { service = $1; sub(/:$/, "", service); next }
	in_services && /^    image:/ {
		ref = $0; sub(/^    image:[ ]*/, "", ref); gsub(/["\047]/, "", ref)
		print service "\t" ref
	}')

# Dockerfiles: tracked and new (not ignored) files named Dockerfile, *.Dockerfile or Dockerfile.*.
while IFS= read -r file; do
	[[ -f "$file" ]] || continue
	while IFS=$'\t' read -r line ref; do
		report "$file:$line FROM" "$ref"
	done < <(awk '
		toupper($1) == "FROM" {
			i = 2
			while (i <= NF && $i ~ /^--/) i++
			image = $i
			if (tolower(image) != "scratch" && !(tolower(image) in stages)) print FNR "\t" image
			if (toupper($(i + 1)) == "AS" && $(i + 2) != "") stages[tolower($(i + 2))] = 1
		}' "$file")
done < <(git ls-files --cached --others --exclude-standard -- \
	'Dockerfile' '*/Dockerfile' '*.Dockerfile' '*/Dockerfile.*' 'Dockerfile.*')

if ((failed)); then
	echo "images-check: $failed of $checked images not pinned by tag and digest (name:tag@sha256:...)"
	exit 1
fi
echo "images-check: all $checked images pinned by tag and digest"
