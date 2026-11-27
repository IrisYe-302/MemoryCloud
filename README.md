# Memory Cloud

- **pi/** — Flask webapp, photo storage, print queue, tests, deployment tools.
- **esp/printer-node/** — Wi-Fi queue client + MXW01 BLE printer firmware.
- **esp/ble-printer-test/** — proven standalone BLE test (type `p` to print).
- **esp/status-panel/** — LCD prototype.
- **docs/** — hosting, account, AI, and device setup guides.

Run Python commands from `pi/`. The existing `.venv` remains at the project root; use `../.venv/bin/python` there. Pi installation remains `/opt/memory-cloud` with data in `/var/lib/memory-cloud`; only the Mac source layout changed.

See `docs/ESP-QUEUE.md` for device setup.

## Local development

Requires Python 3.10 or newer. From the repository root:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r pi/requirements.txt
cp .env.example .env
# Edit .env and replace the setup password before continuing.
set -a
source .env
set +a
PYTHONPATH=pi .venv/bin/python -m gunicorn --workers 1 --threads 4 --bind 127.0.0.1:8000 'app:create_app()'
```

Open http://127.0.0.1:8000. A fresh database needs account setup. AI captions
require an OpenAI API key; ordinary album and preview features do not.
See `docs/CAPTIONS.md` for multilingual font dependencies.

For an existing local database, run `.venv/bin/python pi/deploy/run-mac.py`.
It uses `MEMORY_DATA`, then `mac_data` from the ignored
`data/local-settings.json`, then `data/local`. It refuses to create an empty
recovery database. Relative data paths resolve from the repository root.

Deploy with `bash pi/deploy/push-to-pi.sh USER@PI_HOST`. Alternatively, set
`MEMORY_PI_REMOTE` or put `pi_remote` in `data/local-settings.json`:

```json
{
  "pi_remote": "YOUR_USER@YOUR_PI_HOST",
  "mac_data": "data/local"
}
```

Keep that settings file private. No deployment address is required in source.

## Checks

```bash
cd pi
../.venv/bin/python -m unittest discover -s tests -q
```

The firmware projects use ESP-IDF; see each project's README for build and
hardware instructions. Keep `sdkconfig.defaults` and dependency lockfiles in
Git; local `sdkconfig`, downloaded components, and build output are ignored.

## Git and private data

Git stores source code, tests, and documentation, **not your app data**.
The ignore rules exclude photos and databases in `data/`, recovery archives,
environment files, ESP provisioning JSON, and generated files. Keep separate
backups of app data and server configuration. Do not put secrets or private
photos into source files or static assets: ignore rules cannot detect them.

Before committing, review:

```bash
git status --short
git add README.md .gitignore .gitattributes .env.example docs pi esp
git diff --cached --stat
git diff --cached
```

Only commit after reviewing the staged files. `.gitignore` does not protect
already-tracked files, and `git add -f` bypasses it. Deployment examples use placeholders; keep actual addresses in ignored local
settings and firmware configuration.
