#!/usr/bin/env bash
set -euo pipefail
project=$(cd "$(dirname "$0")/../.." && pwd)
bash "$project/pi/deploy/push-to-pi.sh"
printf 'Open the HTTPS webapp, then Printers → Rename or connect printer. Connect your ESP via USB there.
'
