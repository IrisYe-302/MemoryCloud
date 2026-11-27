"""Run the recovered app locally without changing the Pi deployment settings."""
import os
import json
from pathlib import Path
import secrets
import sys

project = Path(__file__).resolve().parents[2]
settings_path = project / 'data/local-settings.json'
settings = json.loads(settings_path.read_text()) if settings_path.exists() else {}
data = Path(os.environ.get('MEMORY_DATA') or settings.get('mac_data', 'data/local')).expanduser()
if not data.is_absolute():
    data = project / data
if not (data / 'memory.db').is_file():
    sys.exit('Recovered database is missing; refusing to start an empty app.')

os.environ['MEMORY_DATA'] = str(data)
os.environ['MEMORY_HTTPS'] = '0'
# Existing account password hashes remain in the recovered database.
# This bootstrap-only value is not used to replace their passwords.
os.environ.setdefault('MEMORY_PASSWORD', secrets.token_urlsafe(32))
os.chdir(project / 'pi')
print('Memory Cloud: http://127.0.0.1:8000', flush=True)
print('Using recovered Mac data:', data, flush=True)
os.execv(sys.executable, [sys.executable, '-m', 'gunicorn', '--workers', '1',
                        '--threads', '4', '--bind', '127.0.0.1:8000',
                        '--access-logfile', '-', 'app:create_app()'])
