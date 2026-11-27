#!/usr/bin/env bash
# AI-assisted with OpenAI Codex. Installs the web app and simulated printer.
set -euo pipefail
umask 077
if [[ $EUID -ne 0 ]]; then
  echo 'Run with sudo, passing the unpacked app directory.' >&2
  exit 1
fi
source_dir=$(realpath "${1:?Pass the unpacked app directory}")
test -f "$source_dir/app.py"
test -f "$source_dir/data/memory.db"
if ss -ltnH 'sport = :8000' | read -r _; then
  echo 'Port 8000 is in use. Stop the manually started app before installing.' >&2
  exit 1
fi
if [[ -e /var/lib/memory-cloud/memory.db ]]; then
  echo 'An installed database already exists; stopping to preserve it.' >&2
  exit 1
fi
# Install caption/emoji fonts before stopping the running app.
if [[ ! -f /usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc || ! -f /usr/share/fonts/truetype/noto/NotoColorEmoji.ttf ]]; then
  apt-get update
  apt-get install -y --no-install-recommends fonts-noto-cjk fonts-noto-color-emoji
fi
id memory >/dev/null 2>&1 || useradd --system --user-group --home-dir /var/lib/memory-cloud --shell /usr/sbin/nologin memory
install -d -m 755 /opt/memory-cloud
for name in app.py device_api.py access.py ai_captions.py delivery.py imaging.py caption_text.py worker.py requirements.txt; do
  install -m 644 "$source_dir/$name" "/opt/memory-cloud/$name"
done
cp -R "$source_dir/static" /opt/memory-cloud/
chmod -R a+rX /opt/memory-cloud/static
python3 -m venv /opt/memory-cloud/.venv
/opt/memory-cloud/.venv/bin/python -m pip install -r /opt/memory-cloud/requirements.txt
chmod -R a+rX /opt/memory-cloud/.venv
install -d -o memory -g memory -m 700 /var/lib/memory-cloud
cp -R "$source_dir/data/." /var/lib/memory-cloud/
chown -R memory:memory /var/lib/memory-cloud
chmod -R u+rwX,go-rwx /var/lib/memory-cloud
if [[ ! -e /etc/memory-cloud.env ]]; then
  python3 - <<'PY'
import secrets
from pathlib import Path
config = Path('/etc/memory-cloud.env')
config.write_text('MEMORY_DATA=/var/lib/memory-cloud\nMEMORY_PASSWORD=' + secrets.token_urlsafe(32) + '\n')
config.chmod(0o600)
PY
fi
install -m 644 "$source_dir/deploy/memory-web.service" /etc/systemd/system/
install -m 644 "$source_dir/deploy/memory-worker.service" /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now memory-web.service memory-worker.service
sleep 2
systemctl --no-pager --full status memory-web.service memory-worker.service
