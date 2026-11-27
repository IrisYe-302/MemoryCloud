#!/usr/bin/env bash
set -euo pipefail
source_dir=$(cd "$(dirname "$0")/.." && pwd)
[[ $EUID -eq 0 ]] || { echo 'Run with sudo'; exit 1; }
test -f /var/lib/memory-cloud/memory.db
# Install caption/emoji fonts before stopping the running app.
if [[ ! -f /usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc || ! -f /usr/share/fonts/truetype/noto/NotoColorEmoji.ttf ]]; then
  apt-get update
  apt-get install -y --no-install-recommends fonts-noto-cjk fonts-noto-color-emoji
fi
systemctl stop memory-worker memory-web
trap 'systemctl start memory-web memory-worker' EXIT
backup="/var/lib/memory-cloud/before-esp-$(date +%Y%m%d-%H%M%S).db"
python3 - "$backup" <<'PY'
import sqlite3,sys
source=sqlite3.connect('/var/lib/memory-cloud/memory.db')
target=sqlite3.connect(sys.argv[1]);source.backup(target);target.close();source.close()
PY
chmod 600 "$backup"
for file in app.py access.py device_api.py ai_captions.py delivery.py imaging.py caption_text.py worker.py requirements.txt; do
  install -m 644 "$source_dir/$file" "/opt/memory-cloud/$file"
done
cp -R "$source_dir/static/." /opt/memory-cloud/static/
chmod -R a+rX /opt/memory-cloud/static
/opt/memory-cloud/.venv/bin/python -m py_compile /opt/memory-cloud/*.py
printf 'Updated code; preserved accounts, photos, settings, and database.\n'
