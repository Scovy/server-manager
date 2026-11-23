#!/usr/bin/env bash
# Read the stopped container's writable layer. Its existing volume is mounted by name.
set -euo pipefail
container=${1:-homelab_backend}
if [[ $(docker inspect -f '{{.State.Status}}' "$container") != exited ]]; then
    echo "Stop Watchtower and the old backend before migration." >&2
    exit 1
fi
volume=$(docker inspect -f '{{range .Mounts}}{{if and (eq .Type "volume") (eq .Destination "/app/data")}}{{.Name}}{{end}}{{end}}' "$container")
if [[ -z "$volume" ]]; then
    echo "Cannot identify the existing named volume mounted at /app/data." >&2
    exit 1
fi
image=$(docker inspect -f '{{.Image}}' "$container")
script=$(cd -- "$(dirname -- "$0")" && pwd)/migrate-backend-data.py
database=$(docker inspect -f '{{range .Config.Env}}{{println .}}{{end}}' "$container" | sed -n 's/^DATABASE_URL=//p')
case "${database:-sqlite+aiosqlite:///./homelab.db}" in
    sqlite+aiosqlite:///./homelab.db|sqlite+aiosqlite:///homelab.db|sqlite+aiosqlite:////app/homelab.db) location=layer ;;
    sqlite+aiosqlite:///./data/homelab.db|sqlite+aiosqlite:///data/homelab.db|sqlite+aiosqlite:////app/data/homelab.db) location=volume ;;
    *) echo "Custom SQLite path. Verify and migrate this installation's data manually." >&2; exit 1 ;;
esac
for key in MARKETPLACE_APPS_DIR BACKUP_DIR; do
    dir=$(docker inspect -f '{{range .Config.Env}}{{println .}}{{end}}' "$container" | sed -n "s/^${key}=//p")
    expected=apps
    if [[ "$key" == BACKUP_DIR ]]; then expected=backups; fi
    if [[ -n "$dir" && "$dir" != "$expected" && "$dir" != "./$expected" && "$dir" != "/app/$expected" ]]; then
        echo "Custom $key. Verify and migrate its data manually." >&2
        exit 1
    fi
done
docker export "$container" | docker run --rm -i --network none \
    --mount "type=volume,src=$volume,dst=/persist" \
    --mount "type=bind,src=$script,dst=/migrate.py,readonly" \
    --entrypoint python "$image" /migrate.py "$location"
