#!/usr/bin/env bash
set -euo pipefail
source_dir=$(cd "$(dirname "$0")/.." && pwd)
project=$(cd "$source_dir/.." && pwd)
remote=${1:-${MEMORY_PI_REMOTE:-}}
if [[ -z "$remote" && -f "$project/data/local-settings.json" ]]; then
    remote=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("pi_remote", ""))' "$project/data/local-settings.json")
fi
if [[ -z "$remote" || "$remote" == -* || "$remote" == *[[:space:]]* ]]; then
    printf 'Usage: bash pi/deploy/push-to-pi.sh USER@PI_HOST (or set MEMORY_PI_REMOTE)\n' >&2
    exit 2
fi
rsync -av --exclude data --exclude .env --exclude __pycache__ --exclude tests "$source_dir/" "$remote:memory-cloud-update/"
ssh -t "$remote" 'sudo bash ~/memory-cloud-update/deploy/update-pi.sh'
