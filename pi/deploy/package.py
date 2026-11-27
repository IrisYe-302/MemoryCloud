"""Create a consistent, private migration bundle. AI-assisted with OpenAI Codex."""
from pathlib import Path
import shutil
import sqlite3
import tarfile
import tempfile

root = Path(__file__).resolve().parents[1]
output = root / 'data' / 'memory-cloud-pi.tar.gz'
with tempfile.TemporaryDirectory() as temp:
    stage = Path(temp) / 'memory-cloud'
    stage.mkdir()
    for name in ('app.py', 'device_api.py', 'access.py', 'ai_captions.py', 'delivery.py', 'imaging.py', 'caption_text.py', 'worker.py',
                 'requirements.txt'):
        shutil.copy2(root / name, stage / name)
    for name in ('static', 'deploy'):
        shutil.copytree(root / name, stage / name,
                        ignore=shutil.ignore_patterns('__pycache__', 'images'))
    data = stage / 'data'
    (data / 'photos').mkdir(parents=True)
    (data / 'renders').mkdir()
    source = sqlite3.connect(root / 'data' / 'memory.db')
    snapshot = sqlite3.connect(data / 'memory.db')
    source.backup(snapshot)
    source.close()
    with snapshot:
        # Preserve accounts but don't transfer active login sessions/invitation tokens.
        snapshot.execute('DELETE FROM sessions')
        snapshot.execute('DELETE FROM invites')
        snapshot.execute('DELETE FROM auth_attempts')
    photo_ids = snapshot.execute('SELECT photo FROM album_photos UNION SELECT photo FROM jobs').fetchall()
    for (pid,) in photo_ids:
        shutil.copy2(root / 'data' / 'photos' / (pid + '.jpg'), data / 'photos' / (pid + '.jpg'))
    for (job,) in snapshot.execute('SELECT job FROM artifacts'):
        shutil.copy2(root / 'data' / 'renders' / (job + '.png'), data / 'renders' / (job + '.png'))
    assert snapshot.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
    print('Album photos:', snapshot.execute('SELECT COUNT(*) FROM album_photos').fetchone()[0])
    snapshot.close()
    with tarfile.open(output, 'w:gz') as archive:
        archive.add(stage, arcname='memory-cloud')
output.chmod(0o600)
print(f'Created {output} ({output.stat().st_size:,} bytes)')
